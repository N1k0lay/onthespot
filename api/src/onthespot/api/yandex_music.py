import time
import uuid

from yandex_music import Client
from yandex_music.exceptions import NetworkError

from ..otsconfig import config
from ..runtimedata import account_pool, get_logger
from ..utils import conv_list_format


logger = get_logger("api.yandex_music")


def yandex_music_add_account_pt1():
    client = Client()
    return client, client.request_device_code(device_name="OnTheSpot")


def yandex_music_add_account_pt2(client, code):
    deadline = time.monotonic() + code.expires_in
    token = None
    while token is None and time.monotonic() < deadline:
        try:
            token = client.poll_device_token(code.device_code)
        except NetworkError as exc:
            logger.warning("Yandex Music OAuth retry: %s", type(exc).__name__)
        if token is None:
            time.sleep(code.interval)

    if token is None:
        return False

    accounts = config.get("accounts").copy()
    accounts.append(
        {
            "uuid": str(uuid.uuid4()),
            "service": "yandex_music",
            "active": True,
            "login": {"access_token": token.access_token},
        }
    )
    config.set("accounts", accounts)
    config.save()
    return True


def yandex_music_login_user(account):
    logger.info("Logging into Yandex Music account...")
    try:
        client = Client(account["login"]["access_token"]).init()
        status = client.account_status()
        user = status.account if status else None
        account_pool.append(
            {
                "uuid": account["uuid"],
                "username": (
                    getattr(user, "display_name", None)
                    or getattr(user, "login", None)
                    or str(getattr(user, "uid", "Yandex Music"))
                ),
                "service": "yandex_music",
                "status": "active",
                "account_type": "premium"
                if status and status.subscription
                else "free",
                "bitrate": "320k",
                "login": {"client": client},
            }
        )
        return True
    except Exception as exc:
        logger.error("Yandex Music login failed: %s", exc)
        account_pool.append(
            {
                "uuid": account["uuid"],
                "username": "Yandex Music",
                "service": "yandex_music",
                "status": "error",
                "account_type": "N/A",
                "bitrate": "N/A",
                "login": {"client": None},
            }
        )
        return False


def yandex_music_get_token(parsing_index):
    return account_pool[parsing_index]["login"]["client"]


def _cover_url(item):
    cover_uri = getattr(item, "cover_uri", None)
    if cover_uri:
        return f"https://{cover_uri.replace('%%', '600x600')}"
    og_image = getattr(item, "og_image", None)
    if og_image:
        return f"https://{og_image.replace('%%', '600x600')}"
    return ""


def _playlist_id(playlist):
    if playlist.playlist_uuid:
        return f"uuid:{playlist.playlist_uuid}"
    return f"{playlist.owner.uid}:{playlist.kind}"


def yandex_music_get_search_results(client, search_term, content_types):
    results = client.search(search_term, type_="all")
    if not results:
        return []

    limit = config.get("max_search_results")
    output = []
    mappings = (
        ("track", "tracks"),
        ("album", "albums"),
        ("artist", "artists"),
        ("playlist", "playlists"),
    )
    for item_type, attribute in mappings:
        if item_type not in content_types:
            continue
        group = getattr(results, attribute, None)
        for item in list(group.results if group else [])[:limit]:
            if item_type == "track":
                item_id = item.track_id
                item_name = item.title
                item_by = ", ".join(item.artists_name())
                item_url = f"https://music.yandex.ru/track/{item.id}"
            elif item_type == "album":
                item_id = str(item.id)
                item_name = item.title
                item_by = ", ".join(item.artists_name())
                item_url = f"https://music.yandex.ru/album/{item.id}"
            elif item_type == "artist":
                item_id = str(item.id)
                item_name = item.name
                item_by = item.name
                item_url = f"https://music.yandex.ru/artist/{item.id}"
            else:
                item_id = _playlist_id(item)
                item_name = item.title
                item_by = item.owner.name or item.owner.login
                item_url = (
                    f"https://music.yandex.ru/playlists/{item.playlist_uuid}"
                    if item.playlist_uuid
                    else f"https://music.yandex.ru/users/{item.owner.login}/playlists/{item.kind}"
                )
            output.append(
                {
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_by": item_by,
                    "item_type": item_type,
                    "item_service": "yandex_music",
                    "item_url": item_url,
                    "item_thumbnail_url": _cover_url(item),
                }
            )
    return output


def yandex_music_get_track_metadata(client, item_id):
    tracks = client.tracks(item_id)
    if not tracks:
        raise ValueError(f"Yandex Music track not found: {item_id}")
    track = tracks[0]
    album = track.albums[0] if track.albums else None
    position = album.track_position if album else None
    labels = album.labels if album else []
    label = labels[0] if labels else ""
    if not isinstance(label, str):
        label = getattr(label, "name", "")

    return {
        "item_id": track.track_id,
        "title": track.title,
        "artists": conv_list_format(track.artists_name()),
        "album_artists": conv_list_format(album.artists_name()) if album else "",
        "album_name": album.title if album else "",
        "album_type": album.type if album else "",
        "track_number": position.index if position else None,
        "disc_number": position.volume if position else 1,
        "total_discs": 1,
        "total_tracks": album.track_count if album else None,
        "release_year": album.year if album else None,
        "genre": album.genre if album else None,
        "label": label,
        "length": track.duration_ms,
        "explicit": bool(track.explicit or track.content_warning == "explicit"),
        "image_url": _cover_url(track),
        "item_url": f"https://music.yandex.ru/track/{track.id}",
        "is_playable": bool(track.available),
    }


def yandex_music_get_album_track_ids(client, album_id):
    album = client.albums_with_tracks(album_id)
    if not album:
        return []
    return [track.track_id for volume in album.volumes or [] for track in volume]


def yandex_music_get_artist_album_ids(client, artist_id):
    albums = []
    page = 0
    while True:
        result = client.artists_direct_albums(artist_id, page=page, page_size=100)
        page_albums = list(result.albums if result else [])
        albums.extend(str(album.id) for album in page_albums)
        if len(page_albums) < 100:
            return albums
        page += 1


def yandex_music_get_playlist_data(client, playlist_id):
    if playlist_id.startswith("uuid:"):
        playlist = client.playlist(playlist_id.removeprefix("uuid:"))
    else:
        owner, kind = playlist_id.rsplit(":", 1)
        playlist = client.users_playlists(kind, user_id=owner)
    if not playlist:
        raise ValueError(f"Yandex Music playlist not found: {playlist_id}")
    tracks = playlist.fetch_tracks()
    owner = playlist.owner.name or playlist.owner.login
    return playlist.title, owner, [track.track_id for track in tracks]


def yandex_music_get_file_url(client, item_id, target_bitrate=320):
    tracks = client.tracks(item_id)
    if not tracks:
        raise ValueError(f"Yandex Music track not found: {item_id}")
    variants = [
        variant
        for variant in tracks[0].get_download_info()
        if not variant.preview and variant.codec == "mp3"
    ]
    if not variants:
        raise ValueError(f"No full Yandex Music stream is available: {item_id}")
    eligible = [
        variant for variant in variants if variant.bitrate_in_kbps <= target_bitrate
    ]
    selected = max(eligible or variants, key=lambda variant: variant.bitrate_in_kbps)
    return selected.get_direct_link(), selected.codec, selected.bitrate_in_kbps
