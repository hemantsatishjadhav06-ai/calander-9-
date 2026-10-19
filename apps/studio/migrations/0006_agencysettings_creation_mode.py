from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("studio", "0005_private_transport_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="agencysettings",
            name="creation_mode",
            field=models.CharField(
                choices=[("confirm", "Show me the brief first"), ("auto", "Go ahead unless I say stop")],
                db_default="confirm",
                default="confirm",
                help_text=(
                    "How your manager starts a team member's idea: after one tap on the brief, or at once. "
                    "Clients always confirm, and every finished post still waits for approval."
                ),
                max_length=10,
            ),
        ),
    ]
