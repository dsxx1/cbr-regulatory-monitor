"""User-invoked owner entry. Key goes in a URL fragment, never into HTTP logs."""
from pathlib import Path
import webbrowser

key_path=Path(__file__).parent/'runtime/local-data/owner.key'
if not key_path.exists():
    raise SystemExit('Сначала запустите мониторинг через ЗАПУСТИТЬ.cmd')
webbrowser.open('http://localhost:8787/#owner='+key_path.read_text(encoding='ascii').strip())
