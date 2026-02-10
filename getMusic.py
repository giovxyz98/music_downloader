import requests
import json
import base64

def save_file(filename, content):
    with open(filename, "w", encoding='utf-8') as file:
        file.write(content)
    print("File "+filename+" creato con successo!")
    
def get_access_token_from_file(token_path):
    try:
        with open(token_path, "r") as token_file:
            access_token = token_file.read()
            return access_token
    except FileNotFoundError:
        print("Error: "+token_path+" file not found.")
        return None

def get_token_from_credentials(creds_path,token_path):
    with open(creds_path, "r") as f:
        creds = json.load(f)  
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]
    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "client_credentials"
    }
    response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
    if response.status_code == 200:
        access_token = response.json()["access_token"]
        save_file(token_path, access_token)


def get_request(url, token,params):
    headers = {
        "Authorization": f"Bearer {token}"
    }
   

    obj = []
    while url:
        
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print("Errore:", response.status_code, response.text)
            break

        data = response.json()
        obj.extend(data.get("items", []))
        url = data.get("next") 
    return obj
  
#Ritorna una lista di album in formato json con i seguenti campi:
# Nome, ID, Anno, Artisti
def get_all_albums(artista, token):
    url = f"https://api.spotify.com/v1/artists/{artista["ID"]}/albums"
    params = {
        "include_groups": "album",
        "limit": 50,  
        "market": "IT"
    }
    albums = get_request(url, token,params)
    count=1
    result = "["
    for album in albums:
        print(f"Album {count}")
        count=count+1
        artist_names = [artist["name"] for artist in album["artists"]]
        result += (
            '{\n'
            f'"Nome": "{album["name"]}",\n'
            f'"ID": "{album["id"]}",\n'
            f'"Anno": "{album["release_date"][:4]}",\n'
            f'"Artisti": {json.dumps(artist_names, ensure_ascii=False)}\n'
            '},\n'
        )
    result = result[:-2]  # Rimuovi l'ultima virgola
    result += "]"
    return result


#Ritorna una lista di canzoni in base all'album passato nella funzione
def get_album_traks(album, token):
    url = f"https://api.spotify.com/v1/albums/{album}/tracks"
    params = {
        "market": "IT",
        "limit": 2       
    }
    tracks = get_request(url, token,params)
    count=1
    result = "["
    for track in tracks:
        print(f"Track {count}")
        count=count+1
        result += (
            '{\n'
            f'"Nome": "{track["name"]}",\n'
            f'"ID": "{track["id"]}"\n'
            '},\n'
        )
    result = result[:-2]  
    result += "]"
    return result



artista ={"Nome":"Gianni Vezzosi","ID":"4COEDUmSsoXGtz01jMuXrU"}
work_path = "C:\\Users\\Giova\\Music\\"
creds_path = work_path+"spotify_credentials.json"
token_path = work_path+"token.txt"



# get_token_from_credentials(creds_path,token_path)
token=get_access_token_from_file(token_path)
with open(r"C:\Users\Giova\Music\Gianni Vezzosi\albums.json", "r", encoding='utf-8') as albums_file:
    albums = json.load(albums_file)


#da completare si devono salvare con coppia {album: array di canzoni}
for album in albums:
    traks = get_album_traks(album["ID"], token)
    print(album["Nome"])
# save_file(work_path+artista["Nome"]+"\\"+"albums.json", get_all_albums(artista, token))