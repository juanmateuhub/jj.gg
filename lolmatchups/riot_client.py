"""Cliente de la Riot API con control de límites de peticiones y reintentos."""
import collections
import time

import requests

from . import config


class RateLimiter:
    """Respeta varias ventanas de límite a la vez (p. ej. 20/1 s y 100/120 s)."""

    def __init__(self, limits):
        self.windows = [(n, per, collections.deque()) for n, per in limits]

    def wait(self):
        while True:
            now = time.monotonic()
            sleep_for = 0.0
            for n, per, q in self.windows:
                while q and now - q[0] >= per:
                    q.popleft()
                if len(q) >= n:
                    sleep_for = max(sleep_for, per - (now - q[0]) + 0.05)
            if sleep_for <= 0:
                for _, _, q in self.windows:
                    q.append(now)
                return
            time.sleep(sleep_for)


class RiotClient:
    def __init__(self, api_key=None, platform=None):
        api_key = api_key or config.RIOT_API_KEY
        if not api_key:
            raise ValueError("Falta RIOT_API_KEY. Cópiala en el fichero .env (ver README).")
        self.platform = (platform or config.PLATFORM).lower()
        if self.platform not in config.PLATFORM_TO_REGION:
            raise ValueError(f"Servidor desconocido: {self.platform}. Opciones: {', '.join(config.PLATFORM_TO_REGION)}")
        self.region = config.PLATFORM_TO_REGION[self.platform]
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = api_key
        self.limiter = RateLimiter(config.RATE_LIMITS)
        self.requests_made = 0

    def _get(self, url, params=None, max_retries=6):
        for attempt in range(max_retries):
            self.limiter.wait()
            self.requests_made += 1
            try:
                r = self.session.get(url, params=params, timeout=20)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 10)))
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (401, 403):
                raise PermissionError(
                    "Clave de API inválida o caducada (las claves de desarrollo caducan cada 24 h). "
                    "Genera una nueva en developer.riotgames.com y actualiza el .env."
                )
            r.raise_for_status()
        return None

    @property
    def _platform_url(self):
        return f"https://{self.platform}.api.riotgames.com"

    @property
    def _region_url(self):
        return f"https://{self.region}.api.riotgames.com"

    # --- Ligas ---
    def apex_league(self, tier):
        """tier: MASTER, GRANDMASTER o CHALLENGER."""
        return self._get(f"{self._platform_url}/lol/league/v4/{tier.lower()}leagues/by-queue/RANKED_SOLO_5x5")

    def league_entries(self, tier, division, page=1):
        """Jugadores de una liga y división (de HIERRO a DIAMANTE)."""
        return self._get(f"{self._platform_url}/lol/league/v4/entries/RANKED_SOLO_5x5/{tier}/{division}",
                         params={"page": page}) or []

    def rank_by_puuid(self, puuid):
        """Liga actual de un jugador en Solo/Dúo, o None si no está clasificado."""
        entries = self._get(f"{self._platform_url}/lol/league/v4/entries/by-puuid/{puuid}") or []
        for e in entries:
            if e.get("queueType") == "RANKED_SOLO_5x5":
                return e.get("tier"), e.get("rank")
        return None

    def summoner_by_id(self, summoner_id):
        return self._get(f"{self._platform_url}/lol/summoner/v4/summoners/{summoner_id}")

    # --- Partidas ---
    def match_ids(self, puuid, count=20, start=0, start_time=None):
        """IDs de las últimas partidas clasificatorias; start_time (segundos epoch) excluye las anteriores."""
        params = {"queue": config.QUEUE_ID, "start": start, "count": count}
        if start_time:
            params["startTime"] = int(start_time)
        return self._get(f"{self._region_url}/lol/match/v5/matches/by-puuid/{puuid}/ids", params=params) or []

    def match(self, match_id):
        return self._get(f"{self._region_url}/lol/match/v5/matches/{match_id}")

    def timeline(self, match_id):
        return self._get(f"{self._region_url}/lol/match/v5/matches/{match_id}/timeline")
