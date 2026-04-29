import typer

from .commands_reset_db import reset_db
from .commands_shell import shell
from .commands_sync import sync

app = typer.Typer(help="Import alarm data into Postgres")

app.command()(sync)
app.command()(shell)
app.command(name="reset-db")(reset_db)
