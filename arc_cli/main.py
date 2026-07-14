import typer
import pathlib as Path
import sqlite3

app = typer.Typer()

@app.command()
def init():
    if not Path.Path(".arc").exists():
        Path.Path(".arc").mkdir()
        typer.echo("Project initialized.")

        db_path = Path.Path(".arc/arc.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS milestones (
            id INTEGER PRIMARY KEY,
            name TEXT,
            owner TEXT,
            deadline TEXT,
            status TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS dependencies (
            id INTEGER PRIMARY KEY,
            milestone_id INTEGER,
            depends_on_id INTEGER
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS commit_activity (
            id INTEGER PRIMARY KEY,
            file TEXT,
            timestamp TEXT,
            milestone_id INTEGER
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS risk_log (
            id INTEGER PRIMARY KEY,
            milestone_id INTEGER,
            signal TEXT,
            severity TEXT,
            resolved INTEGER
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS nudge_history (
            id INTEGER PRIMARY KEY,
            message TEXT,
            timestamp TEXT,
            team_response TEXT
        )''')

        conn.commit()        
        conn.close()
    else:
        typer.echo("Project already initialized.")

if __name__ == "__main__":
    app()