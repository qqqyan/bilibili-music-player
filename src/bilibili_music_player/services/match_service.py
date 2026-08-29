"""歌单匹配服务:导入来源平台歌曲列表,逐首搜索目标平台,打分选候选。

评分与风控策略移植自 temp/match_songs.py(与原脚本保持一致):
    - 标题匹配度为主门:歌名包含/相似 + 歌手出现在标题或 UP 名里加分
    - 时长容差验证:±5s 通过 / 5-15s 扣分 / >30s 基本排除(顺带滤掉合集)
    - 播放量仅作同曲不同稿之间的决胜(log 缩放,避免热门翻唱压过原唱)
    - 翻唱/cover 降权(原唱优先);合集/盘点/串烧硬排除
    - 请求间隔 1.0-1.8s、每 40 请求歇 30-45s、风控码退避重试后中止

歌手映射表(设置 artist_map):{singer 主键, 各平台名为字段(可多个)},
方向由任务配置(source_platform/target_platform)决定,查询与评分时使用。
"""

import asyncio
import json
import math
import random
import re
import unicodedata
from difflib import SequenceMatcher

from bilibili_api import search

from ..repositories import match_store, playlist_store, settings_store
from ._utils import abs_url, parse_duration, strip_em

# ---------------------------------------------------------------- 常量

AUTO_SCORE = 60  # 自动入列阈值(≤ 归入待人工复核)
MAX_QUERIES = 4  # 每首歌最多尝试几个关键词(含映射名查询)
MAX_PAGES = 2  # 每个关键词最多翻几页
REQUEST_MIN, REQUEST_MAX = 1.0, 1.8  # 搜索请求间隔(秒,防风控)
# 风控防护:命中风控码退避重试,仍失败则中止(断点续跑,不污染结果)
RISK_CODES = (-412, -352)  # 请求被拦截 / 风控校验失败
RISK_BACKOFF = 120  # 命中风控后的退避秒数
REST_EVERY = 40  # 每 N 次请求歇一轮(模拟人工,压低持续频率)
REST_SECONDS = (30, 45)
MAX_CONSECUTIVE_FAILURES = 5  # 连续搜索失败达上限视为被墙,中止

# 硬排除的标题词(合集类,播放时对不上)
_EXCLUDE_WORDS = ("合集", "盘点", "串烧", "一人一首", "精选", "大杂烩", "歌单")
# 翻唱降权词(原唱优先)
_COVER_WORDS = ("翻唱", "翻弹", "cover", "歌ってみた", "remix", "混音", "改编", "重制")


class RiskControlError(Exception):
    """风控拦截且退避重试无效,应中止本轮搜索。"""


class NoJobError(Exception):
    """无匹配任务。"""


class JobBusyError(Exception):
    """任务正在搜索中,禁止该操作。"""


class SongNotFoundError(Exception):
    """任务中找不到该歌曲。"""


# ---------------------------------------------------------------- 归一化

def _norm(s: str) -> str:
    """归一化:全角转半角、小写、去空格与常见成对标点。"""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[【】\[\]()（）「」『』“”\"'’·,，.。/\\|:：\-—~～!！?？]+", "", s)
    return re.sub(r"\s+", "", s)


def _norm_artist(artist: str) -> str:
    """歌手名归一:去 Official 后缀(洛天依Official → 洛天依)。"""
    return _norm(artist).replace("official", "")


def _search_artist(artist: str) -> str:
    """搜索用歌手名:去掉 Official 后缀(B 站标题惯例不带它)。"""
    return re.sub(r"\s*official\s*$", "", artist, flags=re.IGNORECASE).strip()


def _has_all_tokens(haystack: str, tokens: list[str]) -> bool:
    return all(t in haystack for t in tokens if t)


def _dedupe_queries(queries: list[str]) -> list[str]:
    """关键词去重(大小写不敏感,保序),顺带压缩空白。"""
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out


# ---------------------------------------------------------------- 歌手映射

def resolve_target_names(
    artists: list[str],
    artist_map: list[dict],
    source_platform: str,
    target_platform: str,
) -> list[str]:
    """按映射表把来源平台歌手名解析为目标平台名称(原始名,评分侧再归一)。

    行匹配:行的来源平台字段与歌曲任一歌手归一化后相等。
    """
    artist_norms = {_norm_artist(a) for a in artists}
    out: list[str] = []
    for row in artist_map:
        src_names = [_norm_artist(n) for n in row.get(source_platform) or []]
        if not (artist_norms & {n for n in src_names if n}):
            continue
        for n in row.get(target_platform) or []:
            if n and n not in out:
                out.append(n)
    return out


# ---------------------------------------------------------------- 查询构建

def build_queries(
    name: str,
    artists: list[str],
    tns: list[str],
    alia: list[str],
    artist_map: list[dict],
    source_platform: str,
    target_platform: str,
) -> list[str]:
    """生成搜索关键词候选(优先级从高到低),去重不截断(搜索时限 MAX_QUERIES)。"""
    sa = [_search_artist(a) for a in artists]
    aliases = resolve_target_names(artists, artist_map, source_platform, target_platform)
    queries: list[str] = []
    # 1) 主歌手 + 歌名
    queries.append(f"{sa[0]} {name}")
    # 2) 全部歌手 + 歌名(合唱/feat 场景)
    if len(sa) > 1:
        queries.append(f"{' '.join(sa)} {name}")
    # 3) 映射目标平台名 + 歌名
    for al in aliases:
        queries.append(f"{al} {name}")
    # 4) 裸歌名
    queries.append(name)
    # 5) 译名/别名变体(B 站上传可能用译名标题)
    for v in [*tns, *alia]:
        if v and v != name:
            queries.append(f"{sa[0]} {v}")
    for v in [*tns, *alia]:
        if v and v != name:
            queries.append(v)
    return _dedupe_queries(queries)


def live_alias_queries(
    name: str,
    artists: list[str],
    artist_map: list[dict],
    source_platform: str,
    target_platform: str,
) -> list[str]:
    """搜索时用「当前」映射生成的目标平台名查询(映射改动即时生效)。"""
    return [
        f"{al} {name}"
        for al in resolve_target_names(artists, artist_map, source_platform, target_platform)
    ]


# ---------------------------------------------------------------- 打分

def score_candidate(
    title: str,
    up: str,
    dur_s: int,
    play: int,
    song_name: str,
    artists: list[str],
    song_dur_s: float,
    target_aliases: list[str],
) -> tuple[int, str]:
    """对单个搜索结果打分,返回 (得分, 原因描述)。"""
    title_norm = _norm(strip_em(title))
    name_norm = _norm(song_name)
    name_tokens = [t for t in re.split(r"[\s&/]+", name_norm) if t]
    up_norm = _norm(up)
    artist_norms = [_norm_artist(a) for a in artists]
    alias_norms = [_norm_artist(a) for a in target_aliases]
    reasons: list[str] = []

    # 硬排除:合集类标题
    for w in _EXCLUDE_WORDS:
        if w in title_norm:
            return 0, f"标题含「{w}」硬排除"

    # 1) 标题匹配度(主门):歌名包含/词元全中(均要求 ≥2 字,
    #    避免单字歌名「x」因包含关系误命中)/相似度
    if len(name_norm) >= 2 and name_norm in title_norm:
        score = 80
        reasons.append("标题含歌名")
    elif len(name_norm) >= 2 and name_tokens and _has_all_tokens(title_norm, name_tokens):
        score = 80
        reasons.append("标题含歌名全部词元")
    else:
        ratio = SequenceMatcher(None, name_norm, title_norm).ratio()
        score = round(ratio * 80)
        reasons.append(f"相似度{ratio:.2f}")

    # 2) 歌手匹配(标题里提到歌手/映射名,或 UP 就是歌手本人;虚拟歌手的 UP 是 P主)
    artist_hit = next((a for a in artist_norms if a and a in title_norm), None)
    if artist_hit:
        score += 20
        reasons.append(f"标题含歌手「{artist_hit}」")
    else:
        alias_hit = next((a for a in alias_norms if a and a in title_norm), None)
        if alias_hit:
            score += 20
            reasons.append(f"标题含映射歌手「{alias_hit}」")
        elif up_norm and any(a == up_norm for a in artist_norms if a):
            score += 20
            reasons.append("UP 为原歌手")
        elif up_norm and any(a == up_norm for a in alias_norms if a):
            score += 20
            reasons.append(f"UP 为映射歌手「{up_norm}」")

    # 3) 翻唱降权(原唱优先)
    if any(w in title_norm for w in _COVER_WORDS):
        score -= 25
        reasons.append("翻唱降权")

    # 4) 时长容差(顺带滤掉合集:合集时长=总时长,对不上)
    if dur_s > 0 and song_dur_s > 0:
        delta = abs(dur_s - song_dur_s)
        if delta <= 5:
            pass
        elif delta <= 15:
            score -= 15
            reasons.append(f"时长差{delta:.0f}s")
        elif delta <= 30:
            score -= 30
            reasons.append(f"时长差{delta:.0f}s")
        else:
            score -= 60
            reasons.append(f"时长差{delta:.0f}s")

    # 5) 播放量决胜(小权重,不喧宾夺主)
    play_bonus = min(20, round(math.log10(play + 1) * 3))
    score += play_bonus
    reasons.append(f"播放{play}")

    return max(score, 0), " + ".join(reasons)


def to_candidate(it: dict) -> dict:
    """原始搜索结果 → 候选字典(统一字段)。"""
    return {
        "bvid": it["bvid"],
        "title": strip_em(it.get("title") or ""),
        "up": it.get("author") or "",
        "mid": int(it.get("mid") or 0),
        "cover": it.get("pic") or "",
        "duration_s": parse_duration(it.get("duration") or it.get("length")),
        "play": int(it.get("play") or 0),
        "description": strip_em(it.get("description") or ""),  # 视频简介(悬浮详情用)
    }


def score_candidates(song: dict, candidates: list[dict], target_aliases: list[str]) -> list[dict]:
    """候选打分并降序排列(带原因)。"""
    song_dur_s = (song.get("duration_ms") or 0) / 1000
    for c in candidates:
        c["score"], c["reason"] = score_candidate(
            c["title"], c["up"], c["duration_s"], c["play"],
            song["name"], song["artists"], song_dur_s, target_aliases,
        )
    return sorted(candidates, key=lambda x: x["score"], reverse=True)


# ---------------------------------------------------------------- 导入解析

def _new_song(rec: dict, artists: list[str], artist_map: list[dict],
              source_platform: str, target_platform: str) -> dict:
    """组装任务内歌曲记录(未搜索态)。"""
    return {
        "netease_id": rec["netease_id"],
        "name": rec["name"],
        "artists": artists,
        "duration_ms": rec.get("duration_ms") or 0,
        "cover": rec.get("cover") or "",
        "queries": build_queries(rec["name"], artists, rec.get("tns") or [],
                                 rec.get("alia") or [], artist_map,
                                 source_platform, target_platform),
        "status": "pending",
        "chosen": None,
        "manual": False,
        "applied": False,
        "candidates": [],
    }


def parse_netease_json(data: list, artist_map: list[dict],
                       source_platform: str, target_platform: str) -> list[dict]:
    """解析网易云歌单 JSON(数组),按 (歌名, 歌手) 去重保留时长最长。"""
    if not isinstance(data, list) or not data:
        raise ValueError("无法识别为网易云歌单 JSON(空数组或非列表)")
    best: dict[tuple, dict] = {}
    for s in data:
        if not isinstance(s, dict) or not s.get("name") or not isinstance(s.get("ar"), list):
            raise ValueError("无法识别为网易云歌单 JSON(缺少 name/ar 字段)")
        artists = [a["name"] for a in s["ar"] if a.get("name")]
        key = (s["name"], tuple(artists))
        if key not in best or (s.get("dt") or 0) > (best[key].get("dt") or 0):
            best[key] = {
                "netease_id": s["id"], "name": s["name"], "duration_ms": s.get("dt") or 0,
                "tns": s.get("tns") or [], "alia": s.get("alia") or [],
                "cover": (s.get("al") or {}).get("picUrl") or "",
            }
    return [
        _new_song(rec, list(key[1]), artist_map, source_platform, target_platform)
        for key, rec in best.items()
    ]


def parse_seeded_jsonl(text: str, artist_map: list[dict],
                       source_platform: str, target_platform: str) -> list[dict]:
    """解析 temp 脚本产出的结果 JSONL 作为种子任务(不重搜)。

    状态映射:matched+chosen → matched;review → review(chosen 必须清空,
    临时脚本对 review 也写了 chosen);review 无候选 → no_match。
    候选用当前映射重新本地打分。
    """
    by_id: dict[int, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("netease_id") is not None:
            by_id[rec["netease_id"]] = rec
    if not by_id:
        raise ValueError("无法识别为匹配结果 JSONL(无有效记录)")

    songs: list[dict] = []
    for rec in by_id.values():
        artists = list(rec.get("artists") or [])
        aliases = resolve_target_names(artists, artist_map, source_platform, target_platform)
        candidates = score_candidates(rec, list(rec.get("candidates") or []), aliases)[:5]
        status = rec.get("status")
        chosen = None
        if status == "matched" and rec.get("chosen"):
            # 重打分后按 bvid 取回候选(保持得分一致);取不到则沿用原记录
            chosen = next(
                (c for c in candidates if c["bvid"] == rec["chosen"].get("bvid")),
                rec["chosen"],
            )
        elif status != "matched" or not candidates:
            status = "review" if candidates else "no_match"
        songs.append({
            "netease_id": rec["netease_id"],
            "name": rec.get("name") or "",
            "artists": artists,
            "duration_ms": rec.get("duration_ms") or 0,
            "cover": rec.get("cover") or "",
            "queries": build_queries(rec.get("name") or "", artists, [], [],
                                     artist_map, source_platform, target_platform),
            "status": status,
            "chosen": chosen,
            "manual": False,
            "applied": False,
            "candidates": candidates,
        })
    return songs


# ---------------------------------------------------------------- 占位曲目

def _placeholder_track(song: dict) -> dict:
    """任务歌曲 → 播放列表占位条目(id match:{netease_id})。

    播放时由 track plan 端点即时匹配并就地升级为真实 bvid。
    """
    return {
        "id": f"match:{song['netease_id']}",
        "title": song["name"],
        "artist": "、".join(song["artists"]) or "未知歌手",
        "mid": 0,
        "cover": abs_url(song.get("cover") or ""),
        "duration": round((song.get("duration_ms") or 0) / 1000),
        "source": "待匹配",
        "orig_name": song["name"],
        "orig_artists": list(song["artists"]),
        "match_netease_id": song["netease_id"],
    }


# ---------------------------------------------------------------- 搜索抓取

async def _fetch_candidates(query: str, stat: dict) -> list[dict]:
    """按关键词抓取搜索候选(最多 MAX_PAGES 页,页间随机间隔)。

    风控处理:命中风控码退避重试一次,仍失败抛 RiskControlError;
    每 REST_EVERY 次请求歇一轮,压低持续频率。
    """
    from bilibili_api.exceptions import ResponseCodeException

    items: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        for attempt in range(2):
            try:
                res = await search.search_by_type(
                    query,
                    search_type=search.SearchObjectType.VIDEO,
                    page=page,
                    page_size=20,
                )
                break
            except ResponseCodeException as e:
                if e.code in RISK_CODES:
                    if attempt == 0:
                        print(
                            f"[匹配] 风控 {e.code} 命中,退避 {RISK_BACKOFF}s 后重试({query})",
                            flush=True,
                        )
                        await asyncio.sleep(RISK_BACKOFF)
                        continue
                    raise RiskControlError(f"风控 {e.code} 退避后仍失败") from e
                raise
        page_items = res.get("result") or []
        items.extend(to_candidate(it) for it in page_items if it.get("bvid"))
        num_pages = res.get("numPages") or 1
        if page >= num_pages:
            break
        await asyncio.sleep(random.uniform(REQUEST_MIN, REQUEST_MAX))

    stat["requests"] += 1
    if stat["requests"] % REST_EVERY == 0:
        rest = random.uniform(*REST_SECONDS)
        print(f"[匹配] 已 {stat['requests']} 次请求,歇 {rest:.0f}s", flush=True)
        await asyncio.sleep(rest)
    return items


# ---------------------------------------------------------------- 任务管理器

class MatchManager:
    """匹配任务单例管理器(仿 download_manager:Event 唤醒 + 单 worker)。

    单任务:重复导入覆盖;每首歌完成后整文件原子落盘(断点续跑);
    启动时 searching 残留重置为 pending,searching 任务自动续跑。
    """

    def __init__(self) -> None:
        self._job: dict | None = None
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._pause_requested = False
        self._stat: dict = {"requests": 0}  # 节流计数(进程内,重启清零可接受)

    # ---- 生命周期(lifespan 调用) ----

    async def start(self) -> None:
        job = await match_store.load_job()
        if job:
            changed = False
            for s in job.get("songs", []):
                if s.get("status") == "searching":
                    s["status"] = "pending"
                    changed = True
            if changed:
                await match_store.save_job(job)
            self._job = job
            if job.get("status") == "searching":
                self._wake.set()
        if self._worker is None:
            self._worker = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        # 优雅停机:把进行中的曲目复位,下次启动自动续跑
        if self._job:
            changed = False
            for s in self._job.get("songs", []):
                if s.get("status") == "searching":
                    s["status"] = "pending"
                    changed = True
            if changed:
                await match_store.save_job(self._job)

    # ---- 查询 ----

    def get_job(self) -> dict | None:
        return self._job

    def get_summary(self) -> dict | None:
        job = self._job
        if job is None:
            return None
        songs = job.get("songs", [])
        counts: dict[str, int] = {}
        for s in songs:
            st = s.get("status") or "pending"
            counts[st] = counts.get(st, 0) + 1
        current = next((s for s in songs if s.get("status") == "searching"), None)
        return {
            "name": job.get("name") or "",
            "status": job.get("status") or "idle",
            "source_platform": job.get("source_platform") or "netease",
            "target_platform": job.get("target_platform") or "bilibili",
            "total": len(songs),
            "pending": counts.get("pending", 0),
            "matched": counts.get("matched", 0),
            "review": counts.get("review", 0),
            "no_match": counts.get("no_match", 0),
            "applied": sum(1 for s in songs if s.get("applied")),
            "current": {
                "netease_id": current["netease_id"],
                "name": current["name"],
            } if current else None,
            "error": job.get("error") or "",
        }

    # ---- 任务操作 ----

    async def import_job(self, name: str, content: str, source_platform: str = "netease") -> dict:
        """导入(覆盖式)。自动识别网易云 JSON 数组 / 种子 JSONL。"""
        if self._job and self._job.get("status") == "searching":
            raise JobBusyError("搜索进行中,无法导入;请先暂停")
        artist_map = settings_store.load_settings().get("artist_map") or []
        target_platform = "bilibili"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            songs = parse_netease_json(data, artist_map, source_platform, target_platform)
        else:
            songs = parse_seeded_jsonl(content, artist_map, source_platform, target_platform)
        self._job = {
            "name": name,
            "created_at": _now_iso(),
            "source_platform": source_platform,
            "target_platform": target_platform,
            "status": "idle" if any(s["status"] == "pending" for s in songs) else "done",
            "error": "",
            "songs": songs,
        }
        self._pause_requested = False
        await match_store.save_job(self._job)
        return self.get_summary()

    async def start_search(self) -> dict:
        if self._job is None:
            raise NoJobError("暂无匹配任务")
        self._pause_requested = False
        self._job["status"] = "searching"
        await match_store.save_job(self._job)
        self._wake.set()
        return self.get_summary()

    async def pause(self) -> dict:
        if self._job is None:
            raise NoJobError("暂无匹配任务")
        self._pause_requested = True  # 当前曲完成后生效
        return self.get_summary()

    async def resume(self) -> dict:
        return await self.start_search()

    async def reset(self) -> None:
        if self._job and self._job.get("status") == "searching":
            raise JobBusyError("搜索进行中,无法重置;请先暂停")
        self._pause_requested = False
        self._job = None
        await match_store.clear_job()

    async def choose(self, netease_id: int, bvid: str | None) -> dict:
        """人工选择候选(bvid=None 标记无匹配)。选择前用当前映射重打分。"""
        song = self._find_song(netease_id)
        artist_map = settings_store.load_settings().get("artist_map") or []
        aliases = resolve_target_names(
            song["artists"], artist_map,
            self._job["source_platform"], self._job["target_platform"],
        )
        if song.get("candidates"):
            score_candidates(song, song["candidates"], aliases)
        if bvid is None:
            song["status"] = "no_match"
            song["chosen"] = None
            song["manual"] = True
        else:
            cand = next((c for c in song.get("candidates", []) if c["bvid"] == bvid), None)
            if cand is None:
                raise ValueError(f"bvid 不在候选列表中: {bvid}")
            song["chosen"] = cand
            song["status"] = "matched"
            song["manual"] = True
        await match_store.save_job(self._job)
        return song

    async def apply(self, netease_ids: list[int]) -> dict:
        """把选中歌曲的 chosen 候选并入播放列表(按 bvid 去重)。

        歌曲已有占位条目(match:{nid})时**就地升级**该条目(保位置、保 orig 字段);
        真实 bvid 已存在于别处时移除占位,不产生重复。
        """
        if self._job is None:
            raise NoJobError("暂无匹配任务")
        ready: list[dict] = []
        skipped_not_ready = 0
        for nid in netease_ids:
            song = next((s for s in self._job["songs"] if s["netease_id"] == nid), None)
            if song is None or song.get("status") != "matched" or not song.get("chosen"):
                skipped_not_ready += 1
                continue
            ready.append(song)
        existing = await playlist_store.get_playlist()
        existing_ids = {t["id"] for t in existing}
        seen: set[str] = set()
        new_tracks: list[dict] = []
        added = upgraded = removed_duplicates = skipped_duplicates = 0
        changed = False
        for song in ready:
            c = song["chosen"]
            tid = f"bv{c['bvid']}"
            pid = f"match:{song['netease_id']}"
            placeholder = next((t for t in existing if t.get("id") == pid), None)
            if placeholder is not None:
                # 已有占位:真实 bvid 在别处 → 移除占位;否则就地升级
                if tid in existing_ids and placeholder.get("id") != tid:
                    existing.remove(placeholder)
                    existing_ids.discard(pid)
                    removed_duplicates += 1
                else:
                    placeholder["id"] = tid
                    placeholder["title"] = c["title"]
                    placeholder["artist"] = c["up"]
                    placeholder["mid"] = c.get("mid") or 0
                    placeholder["cover"] = abs_url(c.get("cover") or "")
                    placeholder["duration"] = c.get("duration_s") or 0
                    placeholder["source"] = "bilibili 视频"
                    placeholder.setdefault("orig_name", song["name"])
                    placeholder.setdefault("orig_artists", list(song["artists"]))
                    placeholder["match_netease_id"] = song["netease_id"]
                    existing_ids.discard(pid)
                    existing_ids.add(tid)
                    upgraded += 1
                changed = True
                continue
            if tid in existing_ids or tid in seen:
                skipped_duplicates += 1
                continue
            seen.add(tid)
            new_tracks.append({
                "id": tid,
                "title": c["title"],
                "artist": c["up"],
                "mid": c.get("mid") or 0,
                "cover": abs_url(c.get("cover") or ""),
                "duration": c.get("duration_s") or 0,
                "source": "bilibili 视频",
                "orig_name": song["name"],
                "orig_artists": list(song["artists"]),
                "match_netease_id": song["netease_id"],
            })
        if new_tracks:
            existing.extend(new_tracks)
            added = len(new_tracks)
            changed = True
        if changed:
            await playlist_store.save_playlist(existing)
        for song in ready:
            song["applied"] = True
        await match_store.save_job(self._job)
        return {
            "added": added,
            "upgraded": upgraded,
            "removed_duplicates": removed_duplicates,
            "skipped_duplicates": skipped_duplicates,
            "skipped_not_ready": skipped_not_ready,
        }

    async def add_placeholders(self, netease_ids: list[int] | None = None) -> dict:
        """把任务歌曲以占位条目加入播放列表(缺省全部;已存在的跳过)。"""
        if self._job is None:
            raise NoJobError("暂无匹配任务")
        songs = self._job.get("songs", [])
        if netease_ids is not None:
            songs = [s for s in songs if s["netease_id"] in netease_ids]
        existing = await playlist_store.get_playlist()
        existing_ids = {t["id"] for t in existing}
        added = 0
        for song in songs:
            if f"match:{song['netease_id']}" in existing_ids:
                continue
            existing.append(_placeholder_track(song))
            existing_ids.add(f"match:{song['netease_id']}")
            added += 1
        if added:
            await playlist_store.save_playlist(existing)
        return {"added": added}

    async def lazy_resolve(
        self,
        netease_id: int,
        fallback_name: str = "",
        fallback_artists: list[str] | None = None,
    ) -> tuple[str, dict | None]:
        """占位曲目即时匹配:返回 (真实 bv id, 候选字典)。失败抛 ValueError。

        优先级:已有 chosen → 已有候选(高置信才落盘)→ 现场搜索(单次,
        无批量节流,同用户手动搜索)。任务被重置时用播放列表条目的
        fallback 名/歌手现场搜索且不落盘。
        """
        song = None
        if self._job is not None:
            song = next(
                (s for s in self._job["songs"] if s["netease_id"] == netease_id), None
            )

        # 1) 已有确认的选择
        if song is not None and song.get("chosen"):
            return f"bv{song['chosen']['bvid']}", song["chosen"]

        # 2) 已有候选:取第一(高置信且非搜索中才落盘为 chosen)
        if song is not None and song.get("candidates"):
            cand = song["candidates"][0]
            if song.get("status") != "searching" and cand.get("score", 0) >= AUTO_SCORE:
                song["chosen"] = cand
                song["status"] = "matched"
                await match_store.save_job(self._job)
            return f"bv{cand['bvid']}", cand

        # 3) 人工标记无匹配:尊重用户决定
        if song is not None and song.get("manual") and song.get("status") == "no_match":
            raise ValueError("匹配失败:已手动标记无匹配")

        # 4) 现场搜索
        name = song["name"] if song is not None else fallback_name
        artists = song["artists"] if song is not None else (fallback_artists or [])
        if not name:
            raise ValueError("匹配失败:缺少歌名信息")
        artist_map = settings_store.load_settings().get("artist_map") or []
        src = self._job.get("source_platform", "netease") if self._job else "netease"
        if song is not None:
            queries = _dedupe_queries(
                live_alias_queries(name, artists, artist_map, src, "bilibili")
                + list(song.get("queries") or [])
            )[:2]
        else:
            sa = [_search_artist(a) for a in artists]
            queries = _dedupe_queries([f"{sa[0]} {name}" if sa else name, name])
        # 独立计数:1-2 次请求,不会触发批量节流
        stat: dict = {"requests": 0}
        items: list[dict] = []
        for q in queries:
            try:
                got = await _fetch_candidates(q, stat)
            except RiskControlError:
                raise ValueError("匹配失败:搜索被风控拦截")
            except Exception:
                continue
            items.extend(got)
            if got:
                break  # 第一个有结果的查询即止(单搜索语义)
        ranked = score_candidates(
            {"name": name, "artists": artists,
             "duration_ms": song.get("duration_ms") if song else 0},
            items,
            resolve_target_names(artists, artist_map, src, "bilibili"),
        )
        if not ranked:
            raise ValueError("匹配失败:未找到候选")
        cand = ranked[0]
        # 不抢写批量 worker 正在搜的歌;从不把 lazy 结果落成 no_match
        if song is not None and song.get("status") != "searching":
            song["candidates"] = ranked[:5]
            if cand.get("score", 0) >= AUTO_SCORE:
                song["chosen"] = cand
                song["status"] = "matched"
            else:
                song["status"] = "review"
            await match_store.save_job(self._job)
        return f"bv{cand['bvid']}", cand

    async def demote_chosen(self, netease_id: int, bvid: str) -> None:
        """候选视频失效(解析失败)时:清 chosen 降级 review,下次重选/重搜。"""
        if self._job is None:
            return
        song = next((s for s in self._job["songs"] if s["netease_id"] == netease_id), None)
        if song is None or not song.get("chosen"):
            return
        if song["chosen"].get("bvid") == bvid:
            song["chosen"] = None
            song["status"] = "review" if song.get("candidates") else "pending"
            await match_store.save_job(self._job)

    # ---- 内部 ----

    def _find_song(self, netease_id: int) -> dict:
        if self._job is None:
            raise NoJobError("暂无匹配任务")
        song = next((s for s in self._job["songs"] if s["netease_id"] == netease_id), None)
        if song is None:
            raise SongNotFoundError(f"任务中无该歌曲: {netease_id}")
        return song

    async def _worker_loop(self) -> None:
        while True:
            job = self._job
            if job is None or job.get("status") != "searching":
                self._wake.clear()
                await self._wake.wait()
                continue
            if self._pause_requested:
                self._pause_requested = False
                job["status"] = "paused"
                await match_store.save_job(job)
                continue
            song = next((s for s in job.get("songs", []) if s.get("status") == "pending"), None)
            if song is None:
                job["status"] = "done"
                await match_store.save_job(job)
                continue
            song["status"] = "searching"
            await match_store.save_job(job)
            try:
                await self._search_song(job, song)
            except RiskControlError as e:
                job["status"] = "paused"
                job["error"] = str(e)[:200]
                await match_store.save_job(job)
                continue
            await match_store.save_job(job)

    async def _search_song(self, job: dict, song: dict) -> None:
        """单曲搜索:映射查询前置 + 候选打分,写回状态。"""
        artist_map = settings_store.load_settings().get("artist_map") or []
        src, dst = job["source_platform"], job["target_platform"]
        aliases = resolve_target_names(song["artists"], artist_map, src, dst)
        queries = _dedupe_queries(
            live_alias_queries(song["name"], song["artists"], artist_map, src, dst)
            + list(song.get("queries") or [])
        )[:MAX_QUERIES]

        seen: set[str] = set()
        all_candidates: list[dict] = []
        consecutive_failures = 0
        for query in queries:
            try:
                candidates = await _fetch_candidates(query, self._stat)
                consecutive_failures = 0
            except RiskControlError:
                raise
            except Exception as e:
                consecutive_failures += 1
                print(f"[匹配] {song['name']} 搜索失败({query}): {str(e)[:80]}", flush=True)
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise RiskControlError("连续搜索失败,疑似被墙") from e
                continue
            for c in candidates:
                if c["bvid"] not in seen:
                    seen.add(c["bvid"])
                    all_candidates.append(c)
            # 该关键词下已有高置信匹配,不必再试下一个
            ranked_now = score_candidates(song, candidates, aliases)
            if ranked_now and ranked_now[0]["score"] >= AUTO_SCORE:
                break
            await asyncio.sleep(random.uniform(REQUEST_MIN, REQUEST_MAX))

        ranked = score_candidates(song, all_candidates, aliases)
        song["candidates"] = ranked[:5]
        best = ranked[0] if ranked else None
        song["chosen"] = None  # 清空旧值(重搜场景)
        if best and best["score"] >= AUTO_SCORE:
            song["status"] = "matched"
            song["chosen"] = best
        elif ranked:
            song["status"] = "review"
        else:
            song["status"] = "no_match"
        song["manual"] = False
        mark = "✓" if song["status"] == "matched" else "?"
        print(
            f"[匹配] {mark} {song['name']} score={best['score'] if best else '-'}",
            flush=True,
        )
        await asyncio.sleep(random.uniform(REQUEST_MIN, REQUEST_MAX))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


manager = MatchManager()
