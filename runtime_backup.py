"""Consistent offline checkpoint. Credentials and owner sessions are excluded."""
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime,timezone

FILES=('cloud-state.json','news-catalog.json','material-briefs.json','source-cache.json',
       'analysis-queue.json','monitor-settings.json','llm-health.json','custom-sources.json')


def create_backup(root):
    root=Path(root)
    directory=root.parent/'backups';directory.mkdir(exist_ok=True)
    destination=directory/('monitor-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.zip')
    temporary=destination.with_suffix('.partial')
    with tempfile.TemporaryDirectory(prefix='monitor-backup-') as folder:
        snapshot=Path(folder)/'service.sqlite'
        source=sqlite3.connect(root/'service.sqlite');target=sqlite3.connect(snapshot)
        try:source.backup(target)
        finally:target.close();source.close()
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot,'service.sqlite')
            for name in FILES:
                file=root/name
                if file.exists():archive.write(file,name)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:raise ValueError('Проверка резервной копии не пройдена')
    temporary.replace(destination)
    return {'file':str(destination),'bytes':destination.stat().st_size,'verified':True}
