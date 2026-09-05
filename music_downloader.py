"""Entry point del programma: costruisce le dipendenze (cache, ricerca Deezer,
downloader) e le inietta nei controller/manager che orchestrano ricerca, coda
e download, prima di avviare la UI. E' l'unico punto da cui si vede come le
parti del programma si compongono."""
import customtkinter as ctk

from cache import CacheManager
from config import MAX_WORKERS, SEARCH_WORKERS
from downloader import AudioDownloader
from download_manager import DownloadManager
from queue_manager import QueueManager
from search_controller import SearchController
from searcher import MusicSearcher
from app import MusicDownloaderApp


def main():
    cache      = CacheManager()
    searcher   = MusicSearcher()
    downloader = AudioDownloader()

    search_controller = SearchController(searcher, cache)
    queue_manager      = QueueManager()
    download_manager   = DownloadManager(downloader, searcher, cache,
                                         MAX_WORKERS, SEARCH_WORKERS)

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    MusicDownloaderApp(root, search_controller, queue_manager, download_manager, cache)
    root.mainloop()


if __name__ == "__main__":
    main()
