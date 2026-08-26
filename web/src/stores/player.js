import { defineStore } from "pinia";
import {
  deleteCacheTrack,
  getAllCache,
  getCacheStatus,
  getPlaylist,
  localStreamUrl,
  localVideoUrl,
  queueCache,
  resolveTrack,
  savePlaylist,
} from "../api";

const LS_KEY = "bmp-playlist";
const LS_PREF = "bmp-pref";

// 音质高低顺序(与后端 cache_store.QUALITY_ORDER 一致,低 -> 高)
const QUALITY_ORDER = [0, 30216, 30232, 30280, 30251, 30250];

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

export const MODES = [
  { id: "order", label: "顺序播放", icon: "→" },
  { id: "list-loop", label: "列表循环", icon: "⟳" },
  { id: "single-loop", label: "单曲循环", icon: "⟳1" },
  { id: "shuffle", label: "随机播放", icon: "⤨" },
];

export const usePlayerStore = defineStore("player", {
  state: () => {
    const prefs = loadJson(LS_PREF, {});
    return {
      playlist: loadJson(LS_KEY, []),
      currentIndex: -1,
      resolved: null, // 当前曲目的解析结果(ResolvedTrack)
      playing: false,
      currentTime: 0,
      duration: 0, // 以媒体实际时长为准,元数据时长仅作列表展示
      volume: prefs.volume ?? 0.8,
      mode: prefs.mode ?? "list-loop",
      qualityIndex: -1, // 当前 resolved.audio_streams 的索引,-1 = 自动(最高)
      qualityId: -1, // 用户期望音质档 ID(-1 = 自动),跨曲目保持
      videoIndex: -1, // 当前 resolved.video_streams 的索引,-1 = 自动(最高画质)
      videoQualityId: -1, // 用户期望画质档 ID(-1 = 自动),跨曲目保持
      cacheStatus: {}, // track_id -> 缓存状态
      mvEnabled: false,
      mvReady: false,
      error: "",
      shuffleQueue: [],
      _history: [], // 播放历史栈(索引),「上一首」按栈回退,支持连续多次(上限 10000,内存可忽略)
      _audio: null,
      _video: null,
      _syncTimer: null,
      _loading: false,
    };
  },

  getters: {
    currentTrack: (s) =>
      s.currentIndex >= 0 && s.currentIndex < s.playlist.length
        ? s.playlist[s.currentIndex]
        : null,
    currentStream: (s) => {
      if (!s.resolved || !s.resolved.audio_streams?.length) return null;
      const idx =
        s.qualityIndex >= 0
          ? Math.min(s.qualityIndex, s.resolved.audio_streams.length - 1)
          : s.resolved.audio_streams.length - 1;
      return s.resolved.audio_streams[idx];
    },
    currentQualityLabel: (s) => s.resolved?.audio_streams[Math.min(s.qualityIndex >= 0 ? s.qualityIndex : s.resolved.audio_streams.length - 1, s.resolved.audio_streams.length - 1)]?.quality ?? "",
    /** 当前应播放的视频画面流(按期望画质) */
    currentVideoStream: (s) => {
      const streams = s.resolved?.video_streams || [];
      if (!streams.length) return null;
      const idx =
        s.videoIndex >= 0 ? Math.min(s.videoIndex, streams.length - 1) : streams.length - 1;
      return streams[idx];
    },
  },

  actions: {
    // -------------------------------------------------- 媒体元素接线
    attachMedia(audioEl, videoEl) {
      this._audio = audioEl;
      this._video = videoEl;
      audioEl.volume = this.volume;

      audioEl.addEventListener("timeupdate", () => {
        this.currentTime = audioEl.currentTime;
        if (Number.isFinite(audioEl.duration)) this.duration = audioEl.duration;
      });
      audioEl.addEventListener("play", () => (this.playing = true));
      audioEl.addEventListener("pause", () => (this.playing = false));
      audioEl.addEventListener("ended", () => this._onEnded());
      audioEl.addEventListener("error", () => {
        if (!audioEl.src || !this.resolved) return;
        // 本地缓存文件失效(被外部删除等):自动回退远程播放
        if (audioEl.src.includes("/api/local/")) {
          this._fallbackToRemote();
        } else {
          this.error = "音频流播放失败,可尝试切换音质";
        }
      });
      videoEl.addEventListener("error", () => (this.mvReady = false));
      // 首帧可用即可显示画面(不要求正在播放:暂停状态开 MV 也有画面)
      videoEl.addEventListener("loadeddata", () => (this.mvReady = true));
      videoEl.addEventListener("waiting", () => (this.mvReady = false));
    },

    // -------------------------------------------------- 播放列表
    /** 启动时从后端加载歌单;失败时回退浏览器本地缓存(离线兜底) */
    async loadPlaylist() {
      try {
        this.playlist = await getPlaylist();
      } catch {
        this.playlist = loadJson(LS_KEY, []);
        this.error = "无法连接后端,已加载本地缓存的歌单";
      }
      // 策略 A:启动时不自动下载,播放过才下载;「下载全部」按钮手动触发
      await this.refreshCacheStatus();
    },

    /** 拉取全部缓存状态(下载进度等) */
    async refreshCacheStatus() {
      try {
        const data = await getAllCache();
        for (const item of data.items) {
          this.cacheStatus[item.track_id] = item;
        }
      } catch {
        /* 后端不可达静默 */
      }
    },

    /** 以后端持久化为主,localStorage 留作离线兜底 */
    _savePlaylist() {
      localStorage.setItem(LS_KEY, JSON.stringify(this.playlist));
      savePlaylist(this.playlist).catch(() => {
        /* 后端不可达时静默:本地兜底已写入 */
      });
    },
    _savePrefs() {
      localStorage.setItem(
        LS_PREF,
        JSON.stringify({ volume: this.volume, mode: this.mode })
      );
    },

    addTrack(track) {
      if (this.playlist.some((t) => t.id === track.id)) return false; // 已存在
      this.playlist.push(track);
      this._savePlaylist();
      // 策略 A:不自动下载,播放过才会下载(见 playTrack)
      if (this.mode === "shuffle") this._buildShuffleQueue(); // 队列索引同步
      return true;
    },

    removeTrack(index) {
      this.playlist.splice(index, 1);
      if (this.currentIndex === index) {
        this.stop();
        this.currentIndex = -1;
      } else if (this.currentIndex > index) {
        this.currentIndex -= 1;
      }
      // 列表变更后随机队列与历史栈的索引已错位,重建/清空
      if (this.mode === "shuffle") this._buildShuffleQueue();
      this._history = [];
      this._savePlaylist();
    },

    clearPlaylist() {
      this.stop();
      this.playlist = [];
      this.currentIndex = -1;
      this.shuffleQueue = [];
      this._history = [];
      this._savePlaylist();
    },

    stop() {
      this._audio?.pause();
      this._video?.pause();
      this.playing = false;
    },

    // -------------------------------------------------- 播放控制
    /** 播放列表第 index 首。record=false 时不计入播放历史(「上一首」回退用) */
    async playTrack(index, record = true) {
      const track = this.playlist[index];
      if (!track) return;
      if (record && this.currentIndex >= 0 && index !== this.currentIndex) {
        this._history.push(this.currentIndex); // 记住来的地方
        if (this._history.length > 10000) this._history.shift();
      }
      this.currentIndex = index;
      this.resolved = null;
      this.playing = false;
      this.mvEnabled = false;
      this.error = "";
      this._loading = true;
      try {
        // 1) 查询本地缓存状态
        let status = this.cacheStatus[track.id];
        if (!status) {
          status = await getCacheStatus(track.id).catch(() => null);
          if (status) this.cacheStatus[track.id] = status;
        }
        // 2) 音频/视频独立本地优先决策(互不影响,可能混合来源):
        //    本地最高档满足期望 → 用本地;否则远程
        const audioLocal = this._pickLocalStream(
          status?.local_qualities || [],
          this.qualityId,
          QUALITY_ORDER
        );
        const videoLocal = this._pickLocalStream(
          status?.local_videos || [],
          this.videoQualityId,
          null // 视频画质枚举值恰与画质正相关,数值比较即可
        );

        if (!audioLocal) {
          // 音频需远程 → 解析远程,视频有本地则用本地覆盖(独立决策)
          const resolved = await resolveTrack(track.kind, track.id);
          if (this.currentIndex !== index) return; // 用户已切歌,丢弃过期结果
          this.resolved = resolved;
          if (videoLocal) {
            this.resolved.video_streams = this._localVideoStreams(
              track.id,
              status.local_videos
            );
          }
          this._applyQualityId();
          this._applyVideoQualityId();
          this._loadStream();
          // 点播优先:音频未缓存则插队下载
          if (!status?.local_qualities?.length) {
            queueCache([track.id], true).catch(() => {});
          }
        } else {
          // 音频本地 → 不访问 B 站;视频:本地满足用本地,否则留空(开 MV 时懒解析)
          this.resolved = {
            id: track.id,
            kind: track.kind,
            title: track.title,
            artist: track.artist,
            cover: track.cover,
            duration: track.duration,
            source: track.source,
            audio_streams: this._localAudioStreams(track.id, status.local_qualities),
            video_streams: videoLocal
              ? this._localVideoStreams(track.id, status.local_videos)
              : [],
          };
          this._applyQualityId();
          this._applyVideoQualityId();
          this._loadStream();
        }
        await this._audio.play();
      } catch (e) {
        // 3) 远程失败兜底:本地有任何音频档位就播本地(下架/断网也能听)
        const status = this.cacheStatus[track.id];
        if (status?.local_qualities?.length && this.currentIndex === index) {
          this._playLocalOnly(this.playlist[index], status);
          try {
            await this._audio.play();
          } catch {
            this.error = `播放失败: ${e.message}`;
          }
        } else {
          this.error = `解析失败: ${e.message}`;
        }
      } finally {
        this._loading = false;
      }
    },

    /** 本地档位是否满足期望:满足返回应播档位,否则 null(走远程)。
     *  order 为 null 时按档位数值比较(视频画质数值正相关);音质需按顺序表。 */
    _pickLocalStream(quals, wantId, order) {
      if (!quals.length) return null;
      if (wantId < 0) return quals[quals.length - 1]; // 自动:本地最高
      const best = quals[quals.length - 1];
      const bestOrder = order ? order.indexOf(best.quality_id) : best.quality_id;
      const wantOrder = order ? order.indexOf(wantId) : wantId;
      return wantOrder >= 0 && bestOrder >= wantOrder ? best : null;
    },

    _localAudioStreams(trackId, quals) {
      return quals.map((q) => ({
        quality_id: q.quality_id,
        quality: q.quality,
        mime: "audio/mp4",
        bandwidth: 0,
        stream_url: localStreamUrl(trackId, q.quality_id),
      }));
    },

    _localVideoStreams(trackId, vquals) {
      return vquals.map((q) => ({
        quality_id: q.quality_id,
        quality: q.quality,
        mime: "video/mp4",
        bandwidth: 0,
        stream_url: localVideoUrl(trackId, q.quality_id),
      }));
    },

    /** 兜底:仅用本地音频档构造播放源 */
    _playLocalOnly(track, status) {
      this.resolved = {
        id: track.id,
        kind: track.kind,
        title: track.title,
        artist: track.artist,
        cover: track.cover,
        duration: track.duration,
        source: track.source,
        audio_streams: this._localAudioStreams(track.id, status.local_qualities),
        video_streams: this._localVideoStreams(track.id, status.local_videos || []),
      };
      this._applyQualityId();
      this._applyVideoQualityId();
      this._loadStream();
    },

    /** 把期望音质(qualityId)映射为当前 resolved 的档位索引 */
    _applyQualityId() {
      if (!this.resolved?.audio_streams?.length) {
        this.qualityIndex = -1;
        return;
      }
      if (this.qualityId < 0) {
        this.qualityIndex = -1;
        return;
      }
      const idx = this.resolved.audio_streams.findIndex(
        (s) => s.quality_id === this.qualityId
      );
      this.qualityIndex =
        idx >= 0 ? idx : this.resolved.audio_streams.length - 1;
    },

    /** 把期望画质(videoQualityId)映射为当前 resolved 的画质档索引 */
    _applyVideoQualityId() {
      const streams = this.resolved?.video_streams || [];
      if (!streams.length) {
        this.videoIndex = -1;
        return;
      }
      if (this.videoQualityId < 0) {
        this.videoIndex = -1;
        return;
      }
      const idx = streams.findIndex(
        (s) => s.quality_id === this.videoQualityId
      );
      this.videoIndex = idx >= 0 ? idx : streams.length - 1;
    },

    /** 搜索结果直接播放:不存在则先加入列表 */
    async playFromSearch(track) {
      let index = this.playlist.findIndex((t) => t.id === track.id);
      if (index < 0) {
        this.addTrack(track);
        index = this.playlist.length - 1;
      }
      await this.playTrack(index);
    },

    /** 按当前音质装载媒体源 */
    _loadStream() {
      const stream = this.currentStream;
      if (!stream) return;
      this._audio.src = stream.stream_url;
      this._audio.loop = this.mode === "single-loop";
      this.currentTime = 0;
      this._teardownMv();
    },

    toggle() {
      if (!this.currentTrack) return;
      if (this.playing) {
        this.stop();
      } else {
        this._audio?.play();
        if (this.mvEnabled && this.mvReady) this._video?.play();
      }
    },

    async next(auto = false) {
      if (!this.playlist.length) return;
      if (this.mode === "shuffle") {
        if (!this.shuffleQueue.length) this._buildShuffleQueue();
        const idx = this.shuffleQueue.shift();
        if (idx === undefined) return this.stop(); // 列表空
        await this.playTrack(idx);
        return;
      }
      const n = this.playlist.length;
      let idx = this.currentIndex + 1;
      if (idx >= n) {
        if (this.mode === "list-loop" || auto) idx = 0;
        else return this.stop(); // 顺序模式播完停止
      }
      await this.playTrack(idx);
    },

    async prev() {
      if (!this.playlist.length) return;
      // 优先按历史栈回退(随机模式正确回退刚播过的曲目,可连续回退多首);
      // 历史为空时(如刚打开页面),随机模式回退列表上一索引,其余模式循环回退
      if (this._history.length) {
        const idx = this._history.pop();
        await this.playTrack(idx, false);
        return;
      }
      const n = this.playlist.length;
      const idx = (this.currentIndex - 1 + n) % n;
      await this.playTrack(idx, false);
    },

    seek(t) {
      if (this._audio?.src) this._audio.currentTime = t;
      if (this.mvEnabled && this._video?.src) this._video.currentTime = t;
      this.currentTime = t;
    },

    setVolume(v) {
      this.volume = v;
      if (this._audio) this._audio.volume = v;
      this._savePrefs();
    },

    setMode(mode) {
      this.mode = mode;
      this._savePrefs();
      if (this._audio) this._audio.loop = mode === "single-loop";
      if (mode === "shuffle") this._buildShuffleQueue();
    },

    /** 切换音质(保持进度续播,不打断 MV 画面);记住期望音质,跨曲目生效 */
    async setQuality(i) {
      const stream = this.resolved?.audio_streams?.[i];
      if (!stream) return;
      const t = this._audio?.currentTime ?? 0;
      const wasPlaying = this.playing;
      this.qualityIndex = i;
      this.qualityId = stream.quality_id; // 记住期望档,决定后续曲目走本地还是远程
      // 只换音频源,画面独立不受影响
      this._audio.src = stream.stream_url;
      this._audio.loop = this.mode === "single-loop";
      this._audio.currentTime = t;
      if (wasPlaying) await this._audio?.play();
    },

    // -------------------------------------------------- MV 模式
    /** 开启/关闭 MV 画面。视频流为空(本地无画面)时懒解析远程,并补下缓存。 */
    async toggleMv() {
      const track = this.currentTrack;
      if (!track || track.kind !== "video" || !this._video) return;
      this.mvEnabled = !this.mvEnabled;
      if (!this.mvEnabled) {
        this._teardownMv();
        return;
      }
      if (!(this.resolved?.video_streams || []).length) {
        // 懒解析:本地无视频档 → 远程解析画面流
        try {
          const resolved = await resolveTrack(track.kind, track.id);
          if (this.currentTrack?.id !== track.id) return; // 期间已切歌
          this.resolved.video_streams = resolved.video_streams;
          if (!this.resolved.video_streams.length) {
            this.mvEnabled = false;
            this.error = "该视频无 MV 画面";
            return;
          }
          this._applyVideoQualityId();
          queueCache([track.id], true).catch(() => {}); // 补下视频缓存
        } catch (e) {
          this.mvEnabled = false;
          this.error = `MV 解析失败: ${e.message}`;
          return;
        }
      }
      const stream = this.currentVideoStream;
      if (!stream) {
        this.mvEnabled = false;
        this.error = "无可用画面流";
        return;
      }
      // 画面走视频流,声音统一由 audio 元素输出(本地/远程音频均可,时间轴一致)
      this._video.src = stream.stream_url;
      this._video.muted = true;
      this._video.currentTime = this._audio?.currentTime ?? 0;
      if (this.playing) await this._video.play();
      this._startSync();
    },

    /** 切换画质(MV 开启时保持进度续播) */
    async setVideoQuality(i) {
      const stream = this.resolved?.video_streams?.[i];
      if (!stream) return;
      this.videoIndex = i;
      this.videoQualityId = stream.quality_id; // 记住期望画质,跨曲目生效
      if (this.mvEnabled && this._video) {
        const t = this._video.currentTime;
        const wasPlaying = !this._video.paused;
        this._video.src = stream.stream_url;
        this._video.currentTime = t;
        if (wasPlaying) await this._video.play();
      }
    },

    _startSync() {
      clearInterval(this._syncTimer);
      this._syncTimer = setInterval(() => {
        const v = this._video;
        if (!v || !this.mvEnabled || !v.src) return;
        const drift = v.currentTime - (this._audio?.currentTime ?? 0);
        // 画面落后音频过多时校正;画面过快则等音频追上
        if (drift < -0.8 && !v.seeking) v.currentTime = this._audio.currentTime;
      }, 1500);
    },

    _teardownMv() {
      this.mvEnabled = false;
      this.mvReady = false;
      clearInterval(this._syncTimer);
      if (this._video) {
        this._video.pause();
        this._video.removeAttribute("src");
        this._video.load();
      }
    },

    /** 单曲失败后手动重试下载(插队优先) */
    async retryDownload(trackId) {
      await queueCache([trackId], true).catch(() => {});
      this.cacheStatus[trackId] = {
        ...(this.cacheStatus[trackId] || {}),
        state: "pending",
      };
    },

    /** 策略 B:手动下载全部(已缓存的自动跳过,串行限频) */
    async downloadAll() {
      const ids = this.playlist.map((t) => t.id);
      if (!ids.length) return;
      await queueCache(ids).catch(() => {});
      for (const id of ids) {
        this.cacheStatus[id] = {
          ...(this.cacheStatus[id] || {}),
          state: this.cacheStatus[id]?.local_qualities?.length
            ? "done"
            : "pending",
          local_qualities: this.cacheStatus[id]?.local_qualities || [],
        };
      }
      await this.refreshCacheStatus();
    },

    /** 删除单曲本地缓存 */
    async removeCache(trackId) {
      await deleteCacheTrack(trackId).catch(() => {});
      await this.refreshCacheStatus();
    },

    /** 本地缓存文件失效(被删)时自动回退远程播放并重新排队下载 */
    async _fallbackToRemote() {
      if (this._fallingBack) return; // 防 error 事件连续触发重入
      this._fallingBack = true;
      try {
        const track = this.currentTrack;
        if (!track) return;
        this.error = "本地缓存失效,已回退远程播放";
        const t = this._audio?.currentTime ?? 0;
        const wasPlaying = this.playing;
        const resolved = await resolveTrack(track.kind, track.id);
        if (this.currentTrack?.id !== track.id) return; // 期间已切歌
        this.resolved = resolved;
        this._applyQualityId();
        this._applyVideoQualityId();
        this._loadStream();
        if (this._audio) this._audio.currentTime = t;
        if (wasPlaying) await this._audio?.play();
        // 文件已被删,重新排队下载
        queueCache([track.id], true).catch(() => {});
      } catch (e) {
        this.error = `本地缓存失效且远程不可用: ${e.message}`;
      } finally {
        this._fallingBack = false;
      }
    },

    // -------------------------------------------------- 内部
    _onEnded() {
      if (this.mode === "single-loop") return; // audio.loop 已处理
      this.next(true);
    },

    _buildShuffleQueue() {
      const n = this.playlist.length;
      const q = Array.from({ length: n }, (_, i) => i).filter(
        (i) => i !== this.currentIndex
      );
      for (let i = q.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [q[i], q[j]] = [q[j], q[i]];
      }
      this.shuffleQueue = q;
    },
  },
});
