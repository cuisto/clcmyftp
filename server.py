import os
import re
import sys
import asyncio
import json
import subprocess
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeFilename

# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
API_ID = 4919984
API_HASH = 'eab0814f962c8479516020f34f15c1cf'
TARGET_CHANNEL_ID = -1002505204054
TMDB_API_KEY = 'fdf3e8dfc0ed12f609bf64b3b148b293'
REFRESH_INTERVAL = 1800  # 30 minutes

# DOSSIER DE RÉCEPTION DES TORRENTS
DOSSIER_TORRENTS = r"F:\RSS-Downloads"

# TON IDENTIFIANT NETLIFY OFFICIEL
NETLIFY_SITE_ID = "95c1c614-dcd5-48e6-bdbc-4684bf1283a7"
# -------------------------------------------------------------

def liberer_port_8080():
    print("🔍 Vérification du port 8080...")
    try:
        cmd = 'netstat -ano | findstr :8080'
        output = subprocess.check_output(cmd, shell=True).decode('cp1252', errors='ignore')
        
        pids = set()
        for line in output.strip().split('\n'):
            if "LISTENING" in line:
                parts = line.split()
                if parts[1].endswith(':8080'):
                    pids.add(parts[-1])
        
        if not pids:
            print("✅ Le port 8080 est libre. Poursuite de la routine.")
            return

        for pid in pids:
            print(f"⚠️ Port 8080 occupé par le PID : {pid}")
            print(f"🔨 Fermeture forcée de l'application (PID {pid})...")
            subprocess.run(f'taskkill /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
        asyncio.run(asyncio.sleep(2))
        print("✅ Port 8080 nettoyé et libéré !")

    except subprocess.CalledProcessError:
        print("✅ Le port 8080 est libre. Poursuite de la routine.")
    except Exception as e:
        print(f"❌ Impossible de vérifier ou libérer le port 8080 automatiquement : {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    liberer_port_8080()
    os.makedirs(DOSSIER_TORRENTS, exist_ok=True)
    await client.start()
    await generer_page_statique()
    asyncio.create_task(planificateur_mise_a_jour())
    print("=" * 50)
    print("🛡️ Sentinel PRO : Réception des Torrents active !")
    print(f"📁 Destination : {DOSSIER_TORRENTS}")
    print("🌍 Catalogue : https://clcmyftp.netlify.app")
    print("🌍 Envoi Torrent : https://clcmyftp.netlify.app/envoie.html")
    print("=" * 50)
    yield
    await client.disconnect()

app = FastAPI(lifespan=lifespan)
client = TelegramClient('session_user', API_ID, API_HASH)

async def planificateur_mise_a_jour():
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        try:
            await generer_page_statique()
        except Exception as e:
            print(f"❌ Erreur lors du rafraîchissement Netlify : {e}")

def extraire_details(nom_fichier: str):
    nom_sans_ext = os.path.splitext(nom_fichier)[0]
    ext_origine = os.path.splitext(nom_fichier)[1].lower()
    
    resolution = "Inconnue"
    res_match = re.search(r'(2160p|1080p|720p|480p|4k|uhd)', nom_sans_ext, re.IGNORECASE)
    if res_match:
        resolution = res_match.group(1).upper()
    
    langue = "Inconnu"
    lang_match = re.search(r'(truefrench|vff|vf|multi|french|eng|vostfr|vosta)', nom_sans_ext, re.IGNORECASE)
    if lang_match:
        langue = lang_match.group(1).upper()
        if langue in ["TRUEFRENCH", "VFF"]:
            langue = "Français (VFF)"
        elif langue == "VF":
            langue = "Français (VF)"

    num_partie = None
    part_match = re.search(r'part(?:e)?\.?(\d+)|(?:\.)(\d+)(?:\.rar|\.zip|$)', nom_sans_ext + ext_origine, re.IGNORECASE)
    if part_match:
        num_partie = int(part_match.group(1) or part_match.group(2))

    saison_num = None
    saison_ep = ""
    match_se = re.search(r'[sS](\d+)[eE](\d+)|(\d+)x(\d+)', nom_sans_ext)
    if match_se:
        s = match_se.group(1) or match_se.group(3)
        e = match_se.group(2) or match_se.group(4)
        saison_num = int(s)
        saison_ep = f"S{saison_num:02d}E{int(e):02d}"

    titre_recherche = nom_sans_ext
    coupe_match = re.search(r'(.*?)(?:\s|[._])(?:[sS]\d+[eE]\d+|\d+x\d+|\d{4}|1080p|720p|2160p|french|truefrench|multi|bluray|web-dl|x264|h264|repack|part\d+)', nom_sans_ext, re.IGNORECASE)
    if coupe_match:
        titre_recherche = coupe_match.group(1)
    
    titre_recherche = titre_recherche.replace('.', ' ').replace('_', ' ')
    titre_recherche = re.sub(r'\s+', ' ', titre_recherche).strip()

    reste = nom_sans_ext
    if coupe_match:
        reste = nom_sans_ext[len(coupe_match.group(1)):].strip('._ ')
    reste = reste.replace('.', ' ').replace('_', ' ')
    reste = re.sub(r'\s+', ' ', reste).strip()

    return {
        "titre_recherche": titre_recherche if titre_recherche else nom_sans_ext,
        "titre_complet": nom_sans_ext.replace('_', ' ').replace('.', ' '),
        "saison_num": saison_num,
        "saison_ep": saison_ep,
        "resolution": resolution,
        "langue": langue,
        "num_partie": num_partie,
        "reste": reste if reste else "Aucune"
    }

async def chercher_affiche_tmdb(titre: str, est_serie: bool = False):
    type_recherche = "tv" if est_serie else "movie"
    url = f"https://api.themoviedb.org/3/search/{type_recherche}"
    params = {"api_key": TMDB_API_KEY, "query": titre, "language": "fr-FR"}
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(url, params=params, timeout=3.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    resultat = data["results"][0]
                    return {
                        "poster": f"https://image.tmdb.org/t/p/w500{resultat.get('poster_path')}" if resultat.get('poster_path') else "https://via.placeholder.com/500x750?text=Pas+d'affiche",
                        "titre_officiel": resultat.get("name") if est_serie else resultat.get("title")
                    }
    except Exception:
        pass
    return {"poster": "https://via.placeholder.com/500x750?text=Pas+d'affiche", "titre_officiel": titre}

async def generer_page_statique():
    try:
        entity = await client.get_entity(TARGET_CHANNEL_ID)
    except Exception as e:
        print(f"Erreur Telegram : {e}")
        return

    medias = {}
    total_films = 0
    total_series = 0
    total_episodes = 0

    async for message in client.iter_messages(entity, limit=200):
        is_valid_file = False
        original_filename = f"fichier_{message.id}.dat"

        if message.video:
            is_valid_file = True
        elif message.document:
            is_valid_file = True
            
        if is_valid_file:
            if message.document and message.document.attributes:
                for attr in message.document.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        original_filename = attr.file_name
                        break
            
            infos = extraire_details(original_filename)
            
            if infos["saison_ep"]:
                titre_cle = infos["titre_recherche"]
                if titre_cle not in medias:
                    medias[titre_cle] = {"type": "serie", "titre_recherche": titre_cle, "episodes": []}
                medias[titre_cle]["episodes"].append({"id": message.id, "infos": infos})
                total_episodes += 1
            elif infos["num_partie"] is not None:
                titre_cle = infos["titre_recherche"]
                if titre_cle not in medias:
                    medias[titre_cle] = {"type": "film_split", "titre_recherche": titre_cle, "parties": []}
                medias[titre_cle]["parties"].append({"id": message.id, "infos": infos})
            else:
                medias[infos["titre_complet"]] = {"type": "film", "titre_recherche": infos["titre_recherche"], "infos": infos, "id": message.id}
                total_films += 1

    medias_tries = sorted(medias.values(), key=lambda x: x["titre_recherche"].lower())
    tasks = [chercher_affiche_tmdb(item["titre_recherche"], est_serie=(item["type"] == "serie")) for item in medias_tries]
    resultats_tmdb = await asyncio.gather(*tasks)

    for i, item in enumerate(medias_tries):
        item["affiche"] = resultats_tmdb[i]["poster"]
        item["titre_officiel_tmdb"] = resultats_tmdb[i]["titre_officiel"]
        if item["type"] == "serie":
            total_series += 1
        elif item["type"] == "film_split":
            total_films += 1

    series_html = ""
    films_html = ""
    popups_js_data = {}

    for i, item in enumerate(medias_tries):
        if item["type"] == "film":
            inf = item["infos"]
            films_html += f"""
            <div class="card" data-title="{inf['titre_complet'].lower()} {item['titre_officiel_tmdb'].lower()}">
                <img src="{item['affiche']}" alt="Affiche">
                <div class="card-info">
                    <h3>{inf['titre_complet']}</h3>
                    <p class="badge badge-film">Film</p>
                    <div class="details-list">
                        <div>🎬 {inf['titre_complet']}</div>
                        <div>ℹ️ Film complet (1 fichier)</div>
                        <div>💎 {item['titre_officiel_tmdb']}</div>
                        <div>📺 Résolution : {inf['resolution']}</div>
                        <div>🌐 Langue : {inf['langue']}</div>
                        <div>⚙️ Tech : {inf['reste']}</div>
                    </div>
                    <a class="btn" href="http://clc.myftp.biz:8080/download/{item['id']}">📥 Télécharger</a>
                </div>
            </div>
            """
        elif item["type"] == "film_split":
            item["parties"] = sorted(item["parties"], key=lambda p: p["infos"]["num_partie"])
            popups_js_data[i] = {"is_split_film": True, "titre_tmdb": item["titre_officiel_tmdb"], "liste_fichiers": item["parties"]}
            nb_parties = len(item["parties"])
            films_html += f"""
            <div class="card card-serie" onclick="ouvrirPopup({i})" data-title="{item['titre_recherche'].lower()} {item['titre_officiel_tmdb'].lower()}">
                <img src="{item['affiche']}" alt="Affiche">
                <div class="card-info">
                    <h3>{item['titre_officiel_tmdb']}</h3>
                    <p class="badge badge-film" style="background: #ff5722;">Film ({nb_parties} parties RAR)</p>
                    <div class="seasons-container">
                        <span style="font-size: 11px; color: #888; display:block; margin-bottom: 5px;">📦 Statut :</span>
                        <span class="season-tag">Fichiers RAR</span>
                    </div>
                    <button class="btn" style="background: #ff5722;">👁️ Voir les parties</button>
                </div>
            </div>
            """
        else:
            item["episodes"] = sorted(item["episodes"], key=lambda e: e["infos"]["saison_ep"])
            popups_js_data[i] = {"is_split_film": False, "titre_tmdb": item["titre_officiel_tmdb"], "liste_fichiers": item["episodes"]}
            
            saisons_trouvees = set()
            for ep in item["episodes"]:
                if ep["infos"]["saison_num"] is not None:
                    saisons_trouvees.add(ep["infos"]["saison_num"])
            
            saisons_triees = sorted(list(saisons_trouvees))
            saisons_html = ""
            for s_num in saisons_triees:
                saisons_html += f'<span class="season-tag">Saison {s_num:02d}</span> '

            nb_episodes = len(item["episodes"])
            series_html += f"""
            <div class="card card-serie" onclick="ouvrirPopup({i})" data-title="{item['titre_recherche'].lower()} {item['titre_officiel_tmdb'].lower()}">
                <img src="{item['affiche']}" alt="Affiche">
                <div class="card-info">
                    <h3>{item['titre_officiel_tmdb']}</h3>
                    <p class="badge badge-serie">Série ({nb_episodes} ép.)</p>
                    <div class="seasons-container">
                        <span style="font-size: 11px; color: #888; display:block; margin-bottom: 5px;">📅 Dispo :</span>
                        {saisons_html if saisons_html else '<span class="season-tag">Saison Inconnue</span>'}
                    </div>
                    <button class="btn btn-serie">👁️ Voir les épisodes</button>
                </div>
            </div>
            """

    popups_js_json = json.dumps(popups_js_data)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>Sentinel PRO</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #111; color: #fff; margin: 0; padding: 90px 15px 80px 15px; min-height: 100vh; box-sizing: border-box; }}
            header {{ position: fixed; top: 0; left: 0; width: 100%; height: 70px; background: #1a1a1a; display: flex; align-items: center; justify-content: space-between; padding: 0 30px; box-shadow: 0 4px 10px rgba(0,0,0,0.7); z-index: 50; box-sizing: border-box; }}
            .logo {{ font-size: 22px; font-weight: bold; color: #0088cc; letter-spacing: 1px; display: flex; align-items: center; gap: 8px; flex-shrink: 0; text-decoration: none; }}
            .header-right {{ display: flex; align-items: center; gap: 15px; }}
            .search-box {{ position: relative; width: 300px; }}
            .search-box input {{ width: 100%; padding: 10px 15px; background: #2a2a2a; border: 1px solid #444; border-radius: 20px; color: #fff; font-size: 14px; outline: none; transition: border 0.2s; box-sizing: border-box; }}
            .search-box input:focus {{ border-color: #0088cc; background: #333; }}
            .tg-link-btn {{ display: flex; align-items: center; gap: 8px; background: #0088cc; color: #fff; text-decoration: none; padding: 8px 14px; border-radius: 20px; font-size: 13px; font-weight: bold; transition: background 0.2s; border: none; cursor: pointer; }}
            .tg-link-btn:hover {{ background: #006699; }}

            .main-stats-panel {{ max-width: 800px; margin: 40px auto 35px auto; background: linear-gradient(135deg, #1e1e1e 0%, #151515 100%); border: 1px solid #282828; border-radius: 12px; padding: 25px 20px; display: flex; justify-content: space-around; align-items: center; box-shadow: 0 8px 25px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05); text-align: center; }}
            .giant-stat-card {{ flex: 1; position: relative; }}
            .giant-stat-label {{ font-size: 13px; text-transform: uppercase; color: #888; letter-spacing: 1.5px; margin-bottom: 8px; font-weight: 600; }}
            .giant-stat-number {{ font-size: 38px; font-weight: 800; color: #fff; text-shadow: 0 0 15px rgba(0, 136, 204, 0.4); }}
            .giant-divider {{ font-size: 32px; color: #282828; font-weight: 300; line-height: 1; user-select: none; }}

            .section-container {{ max-width: 1400px; margin: 0 auto 40px auto; }}
            .section-title {{ font-size: 20px; font-weight: bold; color: #0088cc; margin-bottom: 20px; padding-bottom: 8px; border-bottom: 2px solid #222; display: flex; align-items: center; gap: 10px; }}
            
            footer {{ position: fixed; bottom: 0; left: 0; width: 100%; height: 50px; background: #1a1a1a; display: flex; align-items: center; justify-content: center; font-size: 13px; color: #666; border-top: 1px solid #252525; z-index: 50; }}
            footer span {{ color: #0088cc; font-weight: bold; }}
            
            .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }}
            
            @media (max-width: 850px) {{
                header {{ padding: 12px 15px; height: auto; flex-direction: column; justify-content: center; gap: 12px; position: absolute; }}
                .header-right {{ flex-direction: column; width: 100%; gap: 10px; }}
                .search-box {{ width: 100%; }}
                body {{ padding-top: 190px; padding-bottom: 70px; }}
                .main-stats-panel {{ margin-top: 20px; flex-direction: column; gap: 20px; padding: 20px 10px; }}
                .giant-divider {{ display: none; }}
                .grid {{ grid-template-columns: 1fr; }}
            }}
            .card {{ background: #1e1e1e; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.5); display: flex; flex-direction: column; transition: transform 0.2s; }}
            .card-serie {{ cursor: pointer; }}
            .card img {{ width: 100%; height: 320px; object-fit: cover; background: #000; }}
            .card-info {{ padding: 15px; display: flex; flex-direction: column; flex-grow: 1; }}
            h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #fff; line-height: 1.3; }}
            .badge {{ display: inline-block; font-size: 11px; padding: 3px 6px; border-radius: 4px; font-weight: bold; width: fit-content; margin-bottom: 10px; }}
            .badge-film {{ background: #e50914; }}
            .badge-serie {{ background: #0088cc; }}
            .seasons-container {{ margin-bottom: 15px; flex-grow: 1; border-top: 1px solid #333; padding-top: 10px; }}
            .season-tag {{ display: inline-block; font-size: 11px; background: #333; color: #ddd; padding: 2px 6px; border-radius: 3px; margin-right: 4px; margin-bottom: 4px; font-weight: 500; }}
            .details-list {{ font-size: 11px; color: #aaa; margin-bottom: 15px; line-height: 1.6; border-top: 1px solid #333; padding-top: 10px; flex-grow: 1; }}
            .details-list div {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 3px; }}
            .btn {{ display: block; text-align: center; background: #0088cc; color: white; text-decoration: none; padding: 12px; border-radius: 6px; font-size: 14px; font-weight: bold; border: none; width: 100%; cursor: pointer; box-sizing: border-box; margin-top: auto; }}
            .modal {{ display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.85); align-items: center; justify-content: center; }}
            .modal-content {{ background: #1e1e1e; padding: 20px; border-radius: 10px; width: 92%; max-width: 650px; max-height: 85vh; overflow-y: auto; position: relative; box-sizing: border-box; }}
            .close-btn {{ position: absolute; top: 12px; right: 15px; font-size: 32px; color: #aaa; cursor: pointer; line-height: 1; }}
            .modal h2 {{ color: #0088cc; margin-top: 0; margin-bottom: 20px; font-size: 22px; }}
            .episode-block {{ background: #282828; border-radius: 6px; padding: 12px; margin-bottom: 12px; border-left: 4px solid #0088cc; }}
            .episode-title-main {{ font-size: 13px; font-weight: bold; color: #fff; line-height: 1.4; }}
        </style>
    </head>
    <body>
        <header>
            <a href="/" class="logo">🛡️ Sentinel <span>PRO</span></a>
            <div class="header-right">
                <div class="search-box"><input type="text" id="searchInput" oninput="filtrerMedias()" placeholder="Rechercher..."></div>
                <a href="/envoie.html" class="tg-link-btn">🚀 Envoyer un Torrent</a>
            </div>
        </header>

        <div class="main-stats-panel" id="globalStatsPanel">
            <div class="giant-stat-card"><div class="giant-stat-label">🎬 Films</div><div class="giant-stat-number">{total_films}</div></div>
            <div class="giant-divider">|</div>
            <div class="giant-stat-card"><div class="giant-stat-label">📺 Séries</div><div class="giant-stat-number">{total_series}</div></div>
            <div class="giant-divider">|</div>
            <div class="giant-stat-card"><div class="giant-stat-label">🎞️ Épisodes</div><div class="giant-stat-number">{total_episodes}</div></div>
        </div>

        <div class="section-container" id="seriesSection">
            <div class="section-title">📺 Séries Télévisées</div>
            <div class="grid" id="seriesGrid">{series_html if series_html else ''}</div>
        </div>

        <div class="section-container" id="filmsSection">
            <div class="section-title">🎬 Films récents</div>
            <div class="grid" id="filmsGrid">{films_html if films_html else ''}</div>
        </div>

        <div id="serieModal" class="modal" onclick="fermerPopupDehors(event)">
            <div class="modal-content">
                <span class="close-btn" onclick="fermerPopup()">&times;</span>
                <h2 id="modalTitle">Nom du Média</h2>
                <div id="modalEpisodesList"></div>
            </div>
        </div>
        <footer>© 2026 — Propulsé par &nbsp;<span>Sentinel PRO</span></footer>
        <script>
            const seriesData = {popups_js_json};
            
            function filtrerMedias() {{
                const input = document.getElementById('searchInput').value.toLowerCase();
                let hasVisibleSeries = false;
                const serieCards = document.querySelectorAll('#seriesGrid .card');
                serieCards.forEach(card => {{
                    const titleData = card.getAttribute('data-title');
                    if (titleData.includes(input)) {{ card.style.display = 'flex'; hasVisibleSeries = true; }} else {{ card.style.display = 'none'; }}
                }});
                
                let hasVisibleFilms = false;
                const filmCards = document.querySelectorAll('#filmsGrid .card');
                filmCards.forEach(card => {{
                    const titleData = card.getAttribute('data-title');
                    if (titleData.includes(input)) {{ card.style.display = 'flex'; hasVisibleFilms = true; }} else {{ card.style.display = 'none'; }}
                }});
                
                document.getElementById('seriesSection').style.display = hasVisibleSeries ? 'block' : 'none';
                document.getElementById('filmsSection').style.display = hasVisibleFilms ? 'block' : 'none';
                document.getElementById('globalStatsPanel').style.display = input.length > 0 ? 'none' : 'flex';
            }}
            
            function ouvrirPopup(index) {{
                const data = seriesData[index];
                document.getElementById('modalTitle').innerText = data.titre_tmdb;
                const container = document.getElementById('modalEpisodesList');
                container.innerHTML = '';
                
                data.liste_fichiers.forEach(file => {{
                    const inf = file.infos;
                    const block = document.createElement('div');
                    block.className = 'episode-block';
                    let sousTitre = data.is_split_film ? '📦 Partie du fichier : Part ' + inf.num_partie : 'ℹ️ Saison / Épisode : ' + inf.saison_ep;
                    let btnColor = data.is_split_film ? 'background: #ff5722;' : '';
                    
                    block.innerHTML = 
                        '<div class="episode-header"><div class="episode-title-main">🎬 ' + inf.titre_complet + '</div></div>' +
                        '<div class="details-list">' +
                            '<div>' + sousTitre + '</div>' +
                            '<div>💎 Nom officiel : ' + data.titre_tmdb + '</div>' +
                            '<div>📺 Résolution : ' + inf.resolution + '</div>' +
                            '<div>🌐 Langue : ' + inf.langue + '</div>' +
                            '<div>⚙️ Infos complémentaires : ' + inf.reste + '</div>' +
                        '</div>' +
                        '<a class="btn" style="' + btnColor + '" href="http://clc.myftp.biz:8080/download/' + file.id + '">📥 Télécharger</a>';
                    container.appendChild(block);
                }});
                document.getElementById('serieModal').style.display = 'flex';
            }}
            function fermerPopup() {{ document.getElementById('serieModal').style.display = 'none'; }}
            function fermerPopupDehors(event) {{ if (event.target.id === 'serieModal') fermerPopup(); }}
        </script>
    </body>
    </html>
    """

    # 2. GENERATION DE LA PAGE D'ENVOI (ENVOIE.HTML)
    envoie_content = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Envoyer un Torrent — Sentinel PRO</title>
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; background: #111; color: #fff; margin: 0; padding: 100px 20px 20px 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; box-sizing: border-box; }
            header { position: fixed; top: 0; left: 0; width: 100%; height: 70px; background: #1a1a1a; display: flex; align-items: center; justify-content: space-between; padding: 0 30px; box-shadow: 0 4px 10px rgba(0,0,0,0.7); z-index: 50; box-sizing: border-box; }
            .logo { font-size: 22px; font-weight: bold; color: #0088cc; letter-spacing: 1px; text-decoration: none; }
            .logo span { color: #fff; }
            .nav-btn { background: #2a2a2a; color: #fff; text-decoration: none; padding: 8px 16px; border-radius: 20px; font-size: 13px; font-weight: bold; border: 1px solid #444; }
            .nav-btn:hover { background: #333; }
            
            .upload-container { background: #1e1e1e; border: 1px solid #2d2d2d; border-radius: 12px; padding: 40px; width: 100%; max-width: 550px; text-align: center; box-shadow: 0 8px 20px rgba(0,0,0,0.5); box-sizing: border-box; }
            h2 { color: #0088cc; margin-top: 0; margin-bottom: 10px; font-size: 24px; }
            p { color: #aaa; font-size: 14px; margin-bottom: 30px; }
            
            .drop-zone { border: 2px dashed #0088cc; background: #151515; padding: 40px 20px; border-radius: 8px; cursor: pointer; transition: background 0.2s, border-color: 0.2s; }
            .drop-zone:hover, .drop-zone.dragover { background: #1c252e; border-color: #00b3ff; }
            .drop-zone-text { color: #eee; font-size: 15px; font-weight: 500; }
            .drop-zone-subtext { color: #666; font-size: 12px; margin-top: 8px; }
            
            #fileInput { display: none; }
            
            .progress-container { display: none; margin-top: 25px; text-align: left; }
            .progress-bar { width: 100%; height: 8px; background: #333; border-radius: 4px; overflow: hidden; margin-top: 8px; }
            .progress-fill { width: 0%; height: 100%; background: #0088cc; transition: width 0.1s; }
            
            .status-msg { margin-top: 20px; font-size: 14px; font-weight: bold; display: none; padding: 12px; border-radius: 6px; }
            .status-success { background: rgba(46, 204, 113, 0.15); color: #2ecc71; border: 1px solid #2ecc71; }
            .status-error { background: rgba(231, 76, 60, 0.15); color: #e74c3c; border: 1px solid #e74c3c; }
        </style>
    </head>
    <body>
        <header>
            <a href="/" class="logo">🛡️ Sentinel <span>PRO</span></a>
            <a href="/" class="nav-btn">⬅️ Retour au Catalogue</a>
        </header>

        <div class="upload-container">
            <h2>Téléverser un fichier Torrent</h2>
            <p>Le fichier sera directement ajouté au dossier de téléchargement local de votre serveur.</p>
            
            <div class="drop-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
                <div class="drop-zone-text">📥 Glissez-déposez votre fichier .torrent ici</div>
                <div class="drop-zone-subtext">ou cliquez pour parcourir vos dossiers</div>
                <input type="file" id="fileInput" accept=".torrent">
            </div>

            <div class="progress-container" id="progressContainer">
                <span id="progressLabel" style="font-size: 13px; color: #aaa;">Envoi en cours...</span>
                <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
            </div>

            <div class="status-msg" id="statusMessage"></div>
        </div>

        <script>
            const dropZone = document.getElementById('dropZone');
            const fileInput = document.getElementById('fileInput');
            const progressContainer = document.getElementById('progressContainer');
            const progressFill = document.getElementById('progressFill');
            const statusMessage = document.getElementById('statusMessage');

            ['dragenter', 'dragover'].forEach(eventName => {
                dropZone.addEventListener(eventName, (e) => { e.preventDefault(); dropZone.classList.add('dragover'); }, false);
            });
            ['dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); }, false);
            });

            dropZone.addEventListener('drop', (e) => {
                const files = e.dataTransfer.files;
                if(files.length > 0) envoyerFichier(files[0]);
            });

            fileInput.addEventListener('change', () => {
                if(fileInput.files.length > 0) envoyerFichier(fileInput.files[0]);
            });

            function envoyerFichier(file) {
                if (!file.name.endsWith('.torrent')) {
                    afficherStatus("Seuls les fichiers .torrent sont autorisés !", false);
                    return;
                }

                statusMessage.style.display = 'none';
                progressContainer.style.display = 'block';
                progressFill.style.width = '0%';

                const formData = new FormData();
                formData.append("file", file);

                const xhr = new XMLHttpRequest();
                xhr.open("POST", "http://clc.myftp.biz:8080/upload-torrent", true);

                xhr.upload.onprogress = function(e) {
                    if (e.lengthComputable) {
                        const pourcent = (e.loaded / e.total) * 100;
                        progressFill.style.width = pourcent + '%';
                    }
                };

                xhr.onload = function() {
                    progressContainer.style.display = 'none';
                    if (xhr.status === 200) {
                        afficherStatus("🎉 Torrent reçu et enregistré avec succès dans le dossier local !", true);
                    } else {
                        afficherStatus("❌ Erreur lors de l'enregistrement du fichier.", false);
                    }
                };

                xhr.onerror = function() {
                    progressContainer.style.display = 'none';
                    afficherStatus("❌ Impossible de joindre le serveur de réception local.", false);
                };

                xhr.send(formData);
            }

            function afficherStatus(msg, estSucces) {
                statusMessage.innerText = msg;
                statusMessage.className = "status-msg " + (estSucces ? "status-success" : "status-error");
                statusMessage.style.display = 'block';
            }
        </script>
    </body>
    </html>
    """

    os.makedirs("site", exist_ok=True)
    with open(os.path.join("site", "index.html"), "w", encoding="utf-8") as f:
        f.write(html_content)
    with open(os.path.join("site", "envoie.html"), "w", encoding="utf-8") as f:
        f.write(envoie_content)
    print("✅ Fichiers index.html et envoie.html locaux générés dans le dossier 'site'.")

    if NETLIFY_SITE_ID:
        try:
            print("🚀 Déploiement groupé vers Netlify en cours...")
            commande = f"netlify deploy --site {NETLIFY_SITE_ID} --dir site --prod"
            subprocess.run(commande, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("🌐 [Netlify] Catalogue + Page d'envoi mis à jour en simultané !")
        except Exception as e:
            print(f"❌ Échec du déploiement Netlify : {e}")

@app.get("/", response_class=HTMLResponse)
async def index():
    if os.path.exists(os.path.join("site", "index.html")):
        with open(os.path.join("site", "index.html"), "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Le catalogue se génère... Rechargez la page.</h1>"

@app.post("/upload-torrent")
async def recevoir_torrent(file: UploadFile = File(...)):
    if not file.filename.endswith('.torrent'):
        raise HTTPException(status_code=400, detail="Fichier .torrent uniquement")
    try:
        nom_propre = os.path.basename(file.filename)
        chemin_sauvegarde = os.path.join(DOSSIER_TORRENTS, nom_propre)
        
        with open(chemin_sauvegarde, "wb") as f_out:
            contenu = await file.read()
            f_out.write(contenu)
            
        print(f"📥 Nouveau torrent intercepté et stocké : {chemin_sauvegarde}")
        return {"status": "success", "destination": chemin_sauvegarde}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'écriture : {str(e)}")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="https://telegram.org/img/favicon.ico")

@app.get("/refresh")
async def refresh_cache():
    await generer_page_statique()
    return HTMLResponse("<h1>Mise à jour effectuée ! <a href='/'>Retour</a></h1>")

@app.get("/download/{message_id}")
async def download_telegram_file(message_id: int):
    try:
        entity = await client.get_entity(TARGET_CHANNEL_ID)
        message = await client.get_messages(entity, ids=message_id)
        if not message or (not message.video and not message.document):
            raise HTTPException(status_code=404, detail="Introuvable")

        original_filename = f"video_{message.id}.mp4"
        if message.document and message.document.attributes:
            for attr in message.document.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    original_filename = attr.file_name
                    break

        async def file_generator():
            async for chunk in client.iter_download(message.media, chunk_size=1024*1024):
                yield chunk

        headers = {"Content-Disposition": f'attachment; filename="{original_filename}"'}
        return StreamingResponse(file_generator(), media_type="application/octet-stream", headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)