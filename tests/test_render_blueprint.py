"""The production deployment: Render runs it, Netlify is the public front door.

``render.yaml`` is read by Render's one-click Blueprint from ``main``, which creates the web
service, the worker, Postgres and Key Value in one go. The first boot must succeed before the owner
copies the old deployment's settings in through Render's API, so nothing the app needs to start may
depend on a value typed into the Blueprint form, and no secret may ever be written into the file.

``deploy/netlify`` is the front door's own Netlify site: its build refuses to proxy anywhere but a
plain https origin, then points every path at the Render web service through a signed proxy rule.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
BLUEPRINT = REPO / "render.yaml"
FRONT_DOOR = REPO / "deploy" / "netlify"

PUBLIC_ORIGIN = "https://sm-bean.netlify.app"
REGION = "singapore"
SECRET_WORDS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return yaml.safe_load(BLUEPRINT.read_text())


def _service(blueprint: dict, name: str) -> dict:
    matches = [service for service in blueprint.get("services", []) if service.get("name") == name]
    assert len(matches) == 1, f"render.yaml must define exactly one service named {name}"
    return matches[0]


def _env(service: dict) -> dict[str, dict]:
    entries = service.get("envVars", [])
    keys = [entry["key"] for entry in entries]
    assert len(keys) == len(set(keys)), f"{service['name']} sets a variable twice"
    return {entry["key"]: entry for entry in entries}


def test_the_blueprint_creates_the_four_resources(blueprint):
    services = {(service["type"], service["name"]) for service in blueprint["services"]}
    assert services == {("web", "sm-bean-web"), ("worker", "sm-bean-worker"), ("keyvalue", "sm-bean-cache")}
    assert [database["name"] for database in blueprint["databases"]] == ["sm-bean-db"]
    database = blueprint["databases"][0]
    # Render takes the major version as a string; an integer is not the same instruction.
    assert database["postgresMajorVersion"] == "16"
    assert database["plan"] == "basic-256mb"


def test_every_resource_lives_where_the_workspaces_are(blueprint):
    for resource in [*blueprint["services"], *blueprint["databases"]]:
        assert resource.get("region") == REGION, f"{resource['name']} is not in {REGION}"


def test_web_and_worker_deploy_only_after_the_checks_pass(blueprint):
    for name in ("sm-bean-web", "sm-bean-worker"):
        service = _service(blueprint, name)
        assert service["autoDeployTrigger"] == "checksPass"
        assert "autoDeploy" not in service, "the deprecated field would contradict autoDeployTrigger"
        assert service["runtime"] == "docker"


def test_the_worker_runs_the_one_worker_for_an_hour_at_a_time(blueprint):
    worker = _service(blueprint, "sm-bean-worker")
    command = worker["dockerCommand"]
    assert "manage.py run_worker --duration 3600" in command
    assert "--keep-locks" not in command, "one worker per database; --keep-locks opts out of the lease"
    assert "healthCheckPath" not in worker
    assert "preDeployCommand" not in worker, "only the web service migrates"


def test_the_web_service_checks_and_migrates_before_it_takes_traffic(blueprint):
    web = _service(blueprint, "sm-bean-web")
    assert web["healthCheckPath"] == "/health/"
    command = web["preDeployCommand"]
    assert "manage.py check --deploy" in command
    assert "manage.py migrate --noinput" in command
    # ``&&`` only means something to a shell; without one the second command never runs.
    assert command.startswith('sh -c "') and command.endswith('"')
    assert command.index("check --deploy") < command.index("migrate")


def test_the_public_address_is_one_origin_everywhere(blueprint):
    env = _env(_service(blueprint, "sm-bean-web"))
    app_url = env["APP_URL"]["value"]
    allowed_hosts = [host.strip() for host in env["ALLOWED_HOSTS"]["value"].split(",")]
    trusted_origins = [origin.strip() for origin in env["CSRF_TRUSTED_ORIGINS"]["value"].split(",")]

    assert app_url == PUBLIC_ORIGIN
    assert urlsplit(app_url).hostname in allowed_hosts
    assert app_url in trusted_origins
    assert "*" not in allowed_hosts
    # The platform adds its own hostname at runtime (RENDER_EXTERNAL_HOSTNAME); it is not written here.
    assert allowed_hosts == ["sm-bean.netlify.app"]
    assert trusted_origins == [PUBLIC_ORIGIN]
    assert env["TELEGRAM_WEBHOOK_BASE_URL"]["value"] == PUBLIC_ORIGIN
    assert env["DEBUG"]["value"] == "false"
    assert env["DJANGO_SETTINGS_MODULE"]["value"] == "config.settings.production"


def _media_storage_pending(blueprint: dict) -> bool:
    return _env(_service(blueprint, "sm-bean-web"))["MEDIA_STORAGE_PENDING"]["value"] == "true"


def test_the_first_boot_needs_nothing_typed_into_the_form(blueprint):
    """Media storage is pending until the bucket exists: the app boots and refuses uploads.

    Once uploads work on R2, the file says MEDIA_STORAGE_PENDING "false" (docs/LIVE_OPERATIONS.md,
    step 3): a lost bucket name then stops the deploy, and a Blueprint created afresh needs the four
    S3 values in its form.
    """
    env = _env(_service(blueprint, "sm-bean-web"))
    assert env["STORAGE_BACKEND"]["value"] == "s3"
    assert env["MEDIA_STORAGE_PENDING"]["value"] in ("true", "false")
    assert env["S3_REGION_NAME"]["value"] == "auto"
    for name in ("S3_BUCKET_NAME", "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        assert env[name] == {"key": name, "sync": False}
    assert env["DATABASE_URL"]["fromDatabase"] == {"name": "sm-bean-db", "property": "connectionString"}
    assert env["REDIS_URL"]["fromService"] == {
        "name": "sm-bean-cache",
        "type": "keyvalue",
        "property": "connectionString",
    }
    for name in ("SECRET_KEY", "ENCRYPTION_KEY_SALT"):
        assert env[name] == {"key": name, "generateValue": True}


def test_no_secret_is_written_into_the_blueprint(blueprint):
    for service in blueprint["services"]:
        for name, entry in _env(service).items():
            if not any(word in name for word in SECRET_WORDS):
                continue
            sources = {"generateValue", "fromService", "fromDatabase", "sync"} & entry.keys()
            assert "value" not in entry, f"{service['name']} writes {name} into the file"
            assert sources, f"{service['name']} gives {name} no source"
            if "sync" in entry:
                assert entry["sync"] is False


def test_the_worker_reads_every_value_from_the_web_service(blueprint):
    """One place to copy the old settings into: the worker can never run on a value the web lacks."""
    web = _env(_service(blueprint, "sm-bean-web"))
    worker = _env(_service(blueprint, "sm-bean-worker"))
    assert set(worker) == set(web)
    direct = {"DJANGO_SETTINGS_MODULE", "DATABASE_URL", "REDIS_URL"}
    for name in direct:
        assert worker[name] == web[name]
    for name in set(web) - direct:
        assert worker[name] == {
            "key": name,
            "fromService": {"name": "sm-bean-web", "type": "web", "envVarKey": name},
        }, f"the worker does not read {name} from the web service"


def test_every_left_blank_value_is_one_the_settings_read(blueprint):
    """A misspelt name in the Blueprint would be a value nobody ever reads."""
    settings_source = (REPO / "config" / "settings" / "base.py").read_text()
    for name, entry in _env(_service(blueprint, "sm-bean-web")).items():
        if name == "DJANGO_SETTINGS_MODULE":
            continue
        assert re.search(rf'["\']{re.escape(name)}["\']', settings_source), f"config/settings never reads {name}"
        if entry.get("sync") is False:
            assert set(entry) == {"key", "sync"}


def test_the_blueprint_trusts_only_the_platforms_private_network(blueprint):
    env = _env(_service(blueprint, "sm-bean-web"))
    assert env["BB_TRUSTED_PROXIES"]["value"] == "10.0.0.0/8"
    assert env["FRONT_DOOR_SIGNING_SECRET"] == {"key": "FRONT_DOOR_SIGNING_SECRET", "sync": False}


def test_the_cache_is_reachable_only_inside_the_platform(blueprint):
    cache = _service(blueprint, "sm-bean-cache")
    assert cache["ipAllowList"] == []


# --- the first boot, whatever Render does with a value left blank ----------------------------------
#
# Render's documentation does not say whether a `sync: false` value left blank in the Blueprint form
# is left out of the service's environment or created with an empty value, nor what a worker's
# fromService link to such a value then holds. Both must boot: these build each service's
# environment from render.yaml both ways and run the production settings in a subprocess.

RENDER_HOSTNAME = "sm-bean-web.onrender.com"
# Stand-ins for what Render fills in. check --deploy never connects to either.
RENDER_DATABASE_URL = "postgres://render:render@127.0.0.1:1/sm_bean"
RENDER_KEY_VALUE_URL = "redis://127.0.0.1:1/0"
# What the owner sets once the R2 bucket exists (docs/LIVE_OPERATIONS.md, step 3).
R2_VALUES = {
    "S3_ENDPOINT_URL": "https://0123456789abcdef.r2.cloudflarestorage.com",
    "S3_BUCKET_NAME": "sm-bean-media",
    "S3_ACCESS_KEY_ID": "stand-in",
    "S3_SECRET_ACCESS_KEY": "stand-in",
}
LEFT_OUT = "left out"
CREATED_EMPTY = "created empty"


def _render_value(entry: dict, web: dict[str, dict], blank: str) -> str | None:
    """The value Render gives one envVars entry right after the Blueprint is created (None: unset)."""
    if "value" in entry:
        return str(entry["value"])
    if entry.get("generateValue"):
        return f"render-generated-{entry['key'].lower()}-{'0123456789abcdef' * 3}"
    if "fromDatabase" in entry:
        assert entry["fromDatabase"] == {"name": "sm-bean-db", "property": "connectionString"}
        return RENDER_DATABASE_URL
    if "fromService" in entry:
        source = entry["fromService"]
        if "property" in source:
            assert source == {"name": "sm-bean-cache", "type": "keyvalue", "property": "connectionString"}
            return RENDER_KEY_VALUE_URL
        assert source["name"] == "sm-bean-web"
        return _render_value(web[source["envVarKey"]], web, blank)
    assert entry.get("sync") is False, f"no way to resolve {entry}"
    return "" if blank == CREATED_EMPTY else None


def _first_boot_environment(blueprint: dict, name: str, blank: str) -> dict[str, str]:
    if (REPO / ".env").exists():
        # The settings read it for whatever the environment lacks; Render never has one (.dockerignore).
        pytest.skip("a local .env would fill in the values Render leaves blank")
    web = _env(_service(blueprint, "sm-bean-web"))
    service = _service(blueprint, name)
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "RENDER": "true"}
    if service["type"] == "web":
        # Render's own runtime values; a worker has no public hostname.
        environment.update({"RENDER_EXTERNAL_HOSTNAME": RENDER_HOSTNAME, "PORT": "10000"})
    for key, entry in _env(service).items():
        value = _render_value(entry, web, blank)
        if value is not None:
            environment[key] = value
    return environment


def _run_production(environment: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=REPO, env=environment, capture_output=True, text=True, timeout=180
    )


@pytest.mark.parametrize("blank", [LEFT_OUT, CREATED_EMPTY])
@pytest.mark.parametrize("name", ["sm-bean-web", "sm-bean-worker"])
def test_the_first_boot_passes_the_deploy_check_with_every_blank_value(blueprint, name, blank):
    """The web service's pre-deploy command and the worker's start command both run check --deploy."""
    environment = _first_boot_environment(blueprint, name, blank)
    if blank == CREATED_EMPTY:
        assert environment["ACCOUNT_EMAIL_VERIFICATION"] == "" and environment["EMAIL_PORT"] == ""
    else:
        assert "ACCOUNT_EMAIL_VERIFICATION" not in environment and "EMAIL_PORT" not in environment
    pending = _media_storage_pending(blueprint)
    if not pending:
        # The file has been switched to fail closed once R2 worked: the bucket is no longer optional.
        environment.update(R2_VALUES)

    result = _run_production(environment, "manage.py", "check", "--deploy")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ERRORS:" not in output and "Traceback" not in output, output
    assert ("smbean.W015" in output) == pending, "W015 says media storage is pending, and only then"


def test_once_r2_works_a_lost_bucket_stops_the_deploy(blueprint):
    """MEDIA_STORAGE_PENDING=false, as docs step 3 says to set once uploads work: no bucket is E004."""
    environment = _first_boot_environment(blueprint, "sm-bean-web", LEFT_OUT)
    environment.update(R2_VALUES, MEDIA_STORAGE_PENDING="false")
    del environment["S3_BUCKET_NAME"]

    result = _run_production(environment, "manage.py", "check", "--deploy")
    assert result.returncode != 0
    assert "smbean.E004" in result.stderr


# Every upper-case setting, reduced to plain data so two processes can be compared.
_DUMP_SETTINGS = """
import json, pathlib
import django
django.setup()
from django.conf import settings

def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("latin-1")
    if isinstance(value, pathlib.PurePath):
        return str(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(repr(plain(item)) for item in value)
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return type(value).__qualname__

print(json.dumps({name: plain(getattr(settings, name)) for name in dir(settings) if name.isupper()}))
"""


@pytest.mark.parametrize("name", ["sm-bean-web", "sm-bean-worker"])
def test_a_blank_value_created_empty_means_the_same_as_one_left_out(blueprint, name):
    """An empty ACCOUNT_EMAIL_VERIFICATION, SITE_NAME or ADMIN_URL is not a value: the default applies."""

    def settings_with(blank: str) -> dict:
        environment = _first_boot_environment(blueprint, name, blank)
        result = _run_production(environment, "-c", _DUMP_SETTINGS)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])

    left_out, created_empty = settings_with(LEFT_OUT), settings_with(CREATED_EMPTY)
    differences = {
        key: {LEFT_OUT: left_out.get(key), CREATED_EMPTY: created_empty.get(key)}
        for key in sorted(set(left_out) | set(created_empty))
        if left_out.get(key) != created_empty.get(key)
    }
    assert differences == {}
    assert left_out["ADMIN_URL"] == "admin/"
    assert left_out["SITE_NAME"] == "SM Bean"


# --- the Netlify front door ------------------------------------------------------------------------


@pytest.fixture
def front_door(tmp_path) -> Path:
    for name in ("netlify.toml", "build.sh"):
        shutil.copy(FRONT_DOOR / name, tmp_path / name)
    return tmp_path


def _build(site: Path, origin: str | None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin"}
    if origin is not None:
        env["RENDER_ORIGIN"] = origin
    return subprocess.run(["bash", "build.sh"], cwd=site, env=env, capture_output=True, text=True, timeout=30)


def test_the_front_door_builds_with_its_own_script():
    config = tomllib.loads((FRONT_DOOR / "netlify.toml").read_text())
    assert config["build"]["command"] == "bash build.sh"
    assert config["build"]["publish"] == "public"


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "   ",
        "http://sm-bean-web.onrender.com",
        "sm-bean-web.onrender.com",
        "https://",
        "https://sm-bean-web.onrender.com/admin",
        "https://sm-bean-web.onrender.com?x=1",
        "https://user:pass@sm-bean-web.onrender.com",
        'https://sm-bean-web.onrender.com"\n[[redirects]]',
        "https://sm-bean-web.onrender.com|evil",
    ],
)
def test_the_front_door_refuses_anything_but_an_https_origin(front_door, origin):
    before = (front_door / "netlify.toml").read_text()
    result = _build(front_door, origin)
    assert result.returncode != 0
    assert "RENDER_ORIGIN" in result.stderr
    assert (front_door / "netlify.toml").read_text() == before


@pytest.mark.parametrize(
    "origin",
    [
        "https://sm-bean-web.onrender.com",
        "https://sm-bean-web.onrender.com/",
        "https://sm-bean-web-x1y2.onrender.com:443",
    ],
)
def test_the_front_door_proxies_every_path_to_render(front_door, origin):
    result = _build(front_door, origin)
    assert result.returncode == 0, result.stderr

    config = tomllib.loads((front_door / "netlify.toml").read_text())
    assert config["redirects"] == [
        {
            "from": "/*",
            "to": f"{origin.rstrip('/')}/:splat",
            "status": 200,
            "force": True,
            # Netlify signs each proxied request with this site variable (X-Nf-Sign), which is how
            # the app tells a visitor sent by the front door from one that went round it.
            "signed": "FRONT_DOOR_SIGNING_SECRET",
        }
    ]
    assert (front_door / "public").is_dir()
    # Netlify reads _redirects before netlify.toml: a catch-all there would win and go unsigned.
    assert not (front_door / "public" / "_redirects").exists()
    assert not (front_door / "_redirects").exists()
