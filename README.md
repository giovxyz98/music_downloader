# Music Downloader

App desktop per scaricare musica in MP3 con i tag ID3. Cerca su YouTube tramite
yt-dlp, sceglie il video più pertinente con un sistema di punteggio e scrive
titolo, artista, album, anno, numero traccia e genere nel file.
Non richiede account né API key.

Due modi di usarla:

- **Programma principale**: cerchi artisti, album e canzoni (metadati da Deezer) e
  scarichi quello che scegli.
- **Download da file txt**: scrivi tu l'elenco di artisti, album e canzoni e
  scarica tutto, senza nessuna API.

---

## Requisiti

- Python 3 (sviluppato e provato con 3.13)
- [FFmpeg](https://ffmpeg.org/download.html) installato e nel PATH
  (nell'eseguibile compilato è già incluso)

## Installazione

```bash
git clone https://github.com/giovxyz98/music_downloader.git
cd music_downloader
pip install -r requirements.txt
```

## Avvio

| Cosa | Comando | Doppio clic |
|---|---|---|
| Programma principale | `python music_downloader.py` | `avvia\start.bat` |
| Download da txt (interfaccia) | `python scarica_da_txt.py` | `avvia\scarica_da_txt.bat` |
| Download da txt (terminale) | `python scarica_da_txt.py lista.txt "D:/Musica"` | |
| Leggere il log | | `apri_log.bat` |

---

## Programma principale

- Ricerca artisti, album e canzoni via API Deezer, navigazione artista → album → tracce
- Coda di download con rimozione singola o svuotamento rapido
- Download parallelo (fino a 3 tracce insieme, `MAX_WORKERS` in `config.json`)
- Cronologia download nel menu, con apertura della cartella con un click
- Menu tasto destro: Vai all'artista, Vai all'album, Scarica album direttamente
- Ordinamento degli album (nome A→Z / Z→A, anno ↑ / ↓) e ricerche recenti in home
- Se il file MP3 esiste già nella cartella di destinazione viene saltato

## Download da file txt

Scrivi un file di testo così (altro esempio in `esempi/lista_esempio.txt`):

```
// Le righe che iniziano con // sono ignorate.

# Subsonica

[Album] Microchip Emozionale (1999)
1. Buncia
2. Sonde | Subsonica | 4:53
3. Tutti i miei sbagli

[Singoli]
Nuova ossessione
```

- `# Nome` apre un artista; sotto `[Album] Titolo (anno)` vanno le tracce
  (numero, artisti e durata sono facoltativi), sotto `[Singoli]` i singoli
- Su disco: `<destinazione>/<Artista>/<Album>/` per gli album, i singoli
  direttamente nella cartella dell'artista
- Per ogni artista viene scritto `report_download.txt` con l'esito di ogni canzone,
  il link YouTube da cui è stata scaricata (con titolo e canale del video) e gli eventuali avvisi
  ("ATTENZIONE: durata video …", "CASO LIMITE …"). Il report si aggiorna dopo ogni
  canzone e, se riprendi un download interrotto, le canzoni già presenti
  mantengono il loro link
- L'interfaccia mostra l'anteprima ad albero, l'avanzamento canzone per canzone,
  il tempo stimato e lo spazio occupato

---

## Come sceglie il video

Per ogni canzone valuta i primi 5 risultati YouTube, assegna un punteggio
(artista e titolo nel titolo del video, canale dell'artista o "Topic", durata
simile alla traccia, parole come *live*, *remix*, *karaoke* che tolgono punti) e
scarica il migliore se supera la soglia minima. Se il download del primo fallisce
prova gli altri in ordine di punteggio. Sotto soglia la canzone non viene
scaricata; i casi dubbi (durata molto diversa, artista assente) si scaricano ma
vengono segnalati nel report.

Tutte le regole, con i valori, sono in `docs/scoring/scoring_spiegazione.txt`.

---

## Log

Un solo file, `dati/music_downloader.log`, per entrambi i modi. Ogni esecuzione è
tra due banner (INIZIO / FINE ESECUZIONE) e ogni canzone ha un blocco con i
candidati, il punteggio e il link scaricato. Il livello si regola con `LOG_LEVEL`
in `config.json` (`INFO` di default, `DEBUG` per vedere il calcolo dello scoring).
`apri_log.bat` apre una pagina per leggerlo con filtro per livello e ricerca.
Dettagli in `docs/log_livelli.txt`.

## Struttura

```
music_downloader.py   programma principale (punto di ingresso)
scarica_da_txt.py     download da txt (punto di ingresso)
logica/               logica senza interfaccia: ricerca, scoring, download, coda
ui/                   interfacce (CustomTkinter)
viewer/               pagina per leggere il log
avvia/                .bat per avviare e per compilare l'eseguibile
esempi/               esempio di file txt
dev/                  test_pipeline.py: prova della ricerca e dello scoring senza scaricare
dati/                 log e cache (creata al primo avvio)
docs/                 note, changelog e documentazione dello scoring
config.json           impostazioni (workers, qualità, soglie di scoring, LOG_LEVEL)
```

## Eseguibile (senza Python)

`avvia\build_exe.bat` crea `dist\MusicDownloader\MusicDownloader.exe` con PyInstaller
(serve `pip install pyinstaller` e `ffmpeg.exe` + `ffprobe.exe` nella cartella indicata
nel .bat). Da exe log, cache e config stanno in `%APPDATA%\MusicDownloader`.

## Dipendenze

| Pacchetto | Versione | Uso |
|---|---|---|
| requests | 2.32.3 | chiamate API Deezer |
| yt-dlp | 2026.8.19 | ricerca e download YouTube |
| mutagen | 1.47.0 | scrittura dei tag ID3 |
| rapidfuzz | 3.12.2 | confronto tra titoli |
| customtkinter | 5.2.2 | interfaccia |
