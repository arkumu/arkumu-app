from huey.contrib.djhuey import db_task

from arkumu.catalog.services.download_previews import DownloadPreviews


@db_task()
def download_previews_task(force=False):
    DownloadPreviews().download_previews(force=force)
