"""The production deployment: Render runs it, Netlify is the public front door.

``render.yaml`` is read by Render's one-click Blueprint from ``main``, which creates the web
service, the worker, Postgres and Key Value in one go. The first boot must succeed before the owner
copies the old deployment's settings in through Render's API, so nothing the app needs to start may
depend on a value typed into the Blueprint form, and no secret may ever be written into the file.

``deploy/netlify`` is the front door's own Netlify site: its build refuses to proxy anywhere but a
plain https origin, then points every path at the Render web service through a signed proxy rule.
"""

import re
import shutil
import subprocess
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


def test_the_first_boot_needs_nothing_typed_into_the_form(blueprint):
    """Media storage is pending until the bucket exists: the app boots and refuses uploads."""
    env = _env(_service(blueprint, "sm-bean-web"))
    assert env["STORAGE_BACKEND"]["value"] == "s3"
    assert env["MEDIA_STORAGE_PENDING"]["value"] == "true"
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
