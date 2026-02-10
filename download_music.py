import yt_dlp
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
import os
from tkinter import messagebox

def scarica_audio_massima_qualita(url):
    opzioni = {
        'format': 'bestaudio/best',
        'outtmpl': '%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }],
        'noplaylist': True,
        'quiet': False,
    }

    try:
        with yt_dlp.YoutubeDL(opzioni) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"Errore nel download: {e}")

def cerca_video_youtube(query):
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        try:
            risultati = ydl.extract_info(f"ytsearch:{query}", download=False)
            if risultati['entries']:
                return risultati['entries'][0]['webpage_url']
        except Exception as e:
            print(f"Errore nella ricerca: {e}")
        return None

def scarica_canzone(nome):
    print(f"\n🔍 Cerco: {nome}")
    url = cerca_video_youtube(nome)
    if url:
        print(f"🎵 Scarico da: {url}")
        scarica_audio_massima_qualita(url)
        print(f"✅ Completato: {nome}")
    else:
        print(f"❌ Nessun risultato per: {nome}")

def get_percorso():
    percorso = None
    current_dir = os.path.dirname(os.path.abspath(__file__)) 
    root = tk.Tk()
    root.withdraw()  
    cartella_selezionata = filedialog.askdirectory(
        title="Seleziona una cartella di destinazione",
        initialdir=str(current_dir)
    )
    if cartella_selezionata:
        percorso= cartella_selezionata
    root.destroy()
    return percorso

def seleziona_tracce_album():
    file = None
    current_dir = os.path.dirname(os.path.abspath(__file__))  
    root = tk.Tk()
    root.withdraw()  
    file_selezionato = filedialog.askopenfilename(
        title="Seleziona un file .txt",
        initialdir=str(current_dir),
        filetypes=[("File di testo", "*.txt")]
    )
    if file_selezionato:
        file = file_selezionato
    root.destroy()
    return file

def crea_finestra_principale():
    root = tk.Tk()
    root.title("Benvenuto nell'app di download musica")
    root.geometry("500x400")

    lista_canzoni = []

    def aggiorna_lista():
        lista_label.config(text="\n".join(lista_canzoni) if lista_canzoni else "Nessuna canzone aggiunta.")

    def abilita_inserimento_canzoni():
        entry_canzone.config(state="normal")
        btn_aggiungi.config(state="normal")
        btn_scarica.config(state="normal")
        entry_cantante.config(state="disabled")
        btn_cantante.config(state="disabled")

    def aggiungi_canzone():
        canzone = entry_canzone.get().strip()
        if canzone:
            lista_canzoni.append(f"{cantante_var.get()} - {canzone}")
            entry_canzone.delete(0, tk.END)
            aggiorna_lista()
        else:
            tk.messagebox.showwarning("Errore", "Inserisci il titolo della canzone!")


    def scarica_importate():
        if lista_canzoni:
            for canzone in lista_canzoni:
                print(f"Scaricando: {canzone}")
            tk.messagebox.showinfo("Download completato", "Tutte le canzoni sono state scaricate!")
            mostra_frame(frame_menu)
        else:
            tk.messagebox.showwarning("Errore", "Nessuna canzone da scaricare!")

    frame_menu = tk.Frame(root)
    frame_menu.pack(fill="both", expand=True)

    label_benvenuto = tk.Label(frame_menu, text="Benvenuto!", font=("Arial", 16))
    label_benvenuto.pack(pady=10)

    label_descrizione = tk.Label(
        frame_menu,
        text="Per scaricare la tua musica, inserisci prima i titoli.\nCome preferisci inserire i titoli?",
        font=("Arial", 12),
        justify="center"
    )
    label_descrizione.pack(pady=10)

    btn_inserisci = tk.Button(frame_menu, text="Inserisci manualmente", command=lambda: mostra_frame(frame_inserisci), width=20)
    btn_inserisci.pack(pady=10)

    btn_importa = tk.Button(frame_menu, text="Importa lista", command=lambda: importa_lista(), width=20)
    btn_importa.pack(pady=10)

    frame_inserisci = tk.Frame(root)

    label_inserisci = tk.Label(frame_inserisci, text="Inserisci i titoli manualmente", font=("Arial", 14))
    label_inserisci.pack(pady=10)

    label_cantante = tk.Label(frame_inserisci, text="Inserisci il nome del cantante:", font=("Arial", 12))
    label_cantante.pack(pady=5)

    cantante_var = tk.StringVar()
    entry_cantante = tk.Entry(frame_inserisci, textvariable=cantante_var, width=30)
    entry_cantante.pack(pady=5)

    btn_cantante = tk.Button(frame_inserisci, text="OK", command=abilita_inserimento_canzoni, width=10)
    btn_cantante.pack(pady=5)

    label_canzone = tk.Label(frame_inserisci, text="Inserisci il titolo della canzone:", font=("Arial", 12))
    label_canzone.pack(pady=5)

    entry_canzone = tk.Entry(frame_inserisci, width=30, state="disabled")
    entry_canzone.pack(pady=5)

    btn_aggiungi = tk.Button(frame_inserisci, text="Aggiungi", command=aggiungi_canzone, width=10, state="disabled")
    btn_aggiungi.pack(pady=5)

    btn_scarica = tk.Button(frame_inserisci, text="Scarica", command=scarica_importate, width=10, state="disabled")
    btn_scarica.pack(pady=5)

    btn_torna_indietro = tk.Button(frame_inserisci, text="Torna al menu", command=lambda: mostra_frame(frame_menu), width=20)
    btn_torna_indietro.pack(pady=10)

    lista_label = tk.Label(frame_inserisci, text="Nessuna canzone aggiunta.", font=("Arial", 10), justify="left")
    lista_label.pack(pady=10)
    
    frame_importa = tk.Frame(root)

    label_importa = tk.Label(frame_importa, text="Lista delle canzoni importate", font=("Arial", 14))
    label_importa.pack(pady=10)

    lista_label_importa = tk.Label(frame_importa, text="Nessuna canzone importata.", font=("Arial", 10), justify="left")
    lista_label_importa.pack(pady=10)

    def aggiorna_lista_importa():
        lista_label_importa.config(text="\n".join(lista_canzoni) if lista_canzoni else "Nessuna canzone importata.")

    btn_scarica_importa = tk.Button(frame_importa, text="Scarica", command=scarica_importate, width=20)
    btn_scarica_importa.pack(pady=10)

    btn_torna_menu_importa = tk.Button(frame_importa, text="Torna al menu", command=lambda: mostra_frame(frame_menu), width=20)
    btn_torna_menu_importa.pack(pady=10)

    def importa_lista():
        file = seleziona_tracce_album()
        if file:
            with open(file, "r", encoding="utf-8") as f:
                righe = f.read().splitlines()
                if righe:
                    cantante = righe[0]  # La prima riga è il nome del cantante
                    canzoni = righe[1:]  # Le altre righe sono le canzoni
                    lista_canzoni.extend([f"{cantante} - {canzone}" for canzone in canzoni])
                    aggiorna_lista_importa()
                    tk.messagebox.showinfo("Importa lista", "Lista importata con successo!")
                    mostra_frame(frame_importa)
                else:
                    tk.messagebox.showwarning("Importa lista", "Il file selezionato è vuoto.")
        else:
            tk.messagebox.showwarning("Importa lista", "Nessun file selezionato.")

    def mostra_frame(frame):
        frame_menu.pack_forget()
        frame_inserisci.pack_forget()
        frame_importa.pack_forget()

        if frame == frame_menu:
            cantante_var.set("")
            entry_cantante.config(state="normal")
            btn_cantante.config(state="normal")
            entry_canzone.delete(0, tk.END)
            entry_canzone.config(state="disabled")
            btn_aggiungi.config(state="disabled")
            btn_scarica.config(state="disabled")
            lista_canzoni.clear()
            aggiorna_lista()
            aggiorna_lista_importa()

        frame.pack(fill="both", expand=True)

    mostra_frame(frame_menu)

    root.mainloop()

crea_finestra_principale()