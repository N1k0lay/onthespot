import unittest

from . import _support  # noqa: F401
from onthespot.api.yandex_music import yandex_music_get_file_url
from onthespot.parse_item import UrlMatcher


class _Variant:
    codec = "mp3"
    direct = False

    def __init__(self, bitrate, preview=False):
        self.bitrate_in_kbps = bitrate
        self.preview = preview

    def get_direct_link(self):
        return f"https://audio.example/{self.bitrate_in_kbps}.mp3"


class _Track:
    def get_download_info(self):
        return [_Variant(320), _Variant(192), _Variant(128, preview=True)]


class _Client:
    def tracks(self, _item_id):
        return [_Track()]


class YandexMusicTest(unittest.TestCase):
    def test_urls_and_download_quality(self):
        matcher = UrlMatcher()
        self.assertEqual(
            matcher.match("https://music.yandex.ru/album/1193829/track/10994777"),
            ("yandex_music", "track", "10994777:1193829"),
        )
        self.assertEqual(
            matcher.match("https://music.yandex.ru/users/test/playlists/42"),
            ("yandex_music", "playlist", "test:42"),
        )
        self.assertEqual(
            matcher.match(
                "https://music.yandex.ru/playlists/0ff770f5-26fd-cf87-9a31-9e8723eda07f"
            ),
            (
                "yandex_music",
                "playlist",
                "uuid:0ff770f5-26fd-cf87-9a31-9e8723eda07f",
            ),
        )
        self.assertEqual(
            matcher.match(
                "https://music.yandex.ru/playlists/lk.10ed670a-5496-4b27-9504-2481dfe3c79c"
            ),
            (
                "yandex_music",
                "playlist",
                "uuid:lk.10ed670a-5496-4b27-9504-2481dfe3c79c",
            ),
        )

        url, codec, bitrate = yandex_music_get_file_url(_Client(), "1", 200)
        self.assertEqual(url, "https://audio.example/192.mp3")
        self.assertEqual((codec, bitrate), ("mp3", 192))


if __name__ == "__main__":
    unittest.main()
