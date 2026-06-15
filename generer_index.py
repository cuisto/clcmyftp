import asyncio
from telethon import TelegramClient
from jinja2 import Template

# CONFIGURATION
API_ID = 4919984
API_HASH = 'eab0814f962c8479516020f34f15c1cf'
# Pour les embeds, il faut utiliser le NOM d'utilisateur public du canal (sans le -100)
# Exemple : 'KeBeKois_CLC' (si le canal est public)
CHANNEL_USERNAME = 'KeBeKois_CLC' 

html_template = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Galerie Vidéo Telegram</title>
    <style>
        body { font-family: Arial, sans-serif; background-color: #1a1a1a; color: #fff; margin: 20px; }
        h1 { text-align: center; color: #0088cc; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 20px; padding: 20px; }
        .video-card { background: #2c2c2c; border-radius: 8px; padding: 15px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); text-align: center; }
        iframe { border: none; width: 100%; min-height: 400px; }
    </style>
</head>
<body>

    <h1>Vidéos de {{ channel_username }}</h1>
    
    <div class="grid">
        {% for embed_url in embeds %}
        <div class="video-card">
            <iframe src="{{ embed_url }}" allowtransparency="true" frameborder="0" scrolling="no"></iframe>
        </div>
        {% endfor %}
    </div>

</body>
</html>
"""

async def main():
    client = TelegramClient('session_user', API_ID, API_HASH)
    await client.start()
    
    embeds_urls = []
    
    print(f"Récupération des liens d'intégration...")
    # On récupère l'historique sans rien télécharger
    async for message in client.iter_messages(CHANNEL_USERNAME, limit=50):
        if message.video:
            # Format officiel Telegram pour intégrer un message : https://t.me/nom_canal/id_message?embed=1
            embed_url = f"https://t.me/{CHANNEL_USERNAME}/{message.id}?embed=1"
            embeds_urls.append(embed_url)

    # Génération du HTML
    template = Template(html_template)
    rendered_html = template.render(channel_username=CHANNEL_USERNAME, embeds=embeds_urls)
    
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(rendered_html)
        
    print(" index.html généré avec les lecteurs Telegram intégrés !")
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())