import { defineStore } from "pinia";
import {
  cleanupCache,
  clearCache,
  deleteCacheTrack,
  getAllCache,
  getPlaylist,
  getSettings,
  playUrl,
  queueCache,
  savePlaylist,
  saveSettings,
  trackPlan,
} from "../api";

const LS_KEY = "bmp-playlist";
const LS_PREF = "bmp-pref";

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
      cacheTotalSize: 0, // 本地缓存占用(字节)
      settings: { cleanup_old_quality: false },
      mvEnabled: false,
      mvReady: false,
      _tearingDown: false,
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
        // 统一播放端点:后端自动路由本地/在线(本地被删会落回远程),无需前端回退
        this.error = "音频流播放失败,可尝试切换音质";
      });
      videoEl.addEventListener("error", () => (this.mvReady = false));
      // 首帧可用即可显示画面(不要求正在播放:暂停状态开 MV 也有画面)
      videoEl.addEventListener("loadeddata", () => (this.mvReady = true));
      // seek 后缓冲完成触发 canplay(loadeddata 仅首次加载触发一次),
      // 必须监听它恢复画面,否则「缓冲中」会一直挂着
      videoEl.addEventListener("canplay", () => (this.mvReady = true));
      videoEl.addEventListener("playing", () => (this.mvReady = true));
      videoEl.addEventListener("waiting", () => (this.mvReady = false));
      // 音画双向同步:用户在画面控制条上的操作同步到音频
      videoEl.addEventListener("pause", () => {
        if (this._tearingDown || !this.mvEnabled) return;
        if (this._audio && !this._audio.paused) {
          this._audio.pause();
          this.playing = false;
        }
      });
      videoEl.addEventListener("play", () => {
        if (this._tearingDown || !this.mvEnabled) return;
        if (this._audio?.paused) this._audio.play();
      });
      videoEl.addEventListener("seeked", () => {
        if (this._tearingDown || !this.mvEnabled) return;
        if (this._audio && !this._audio.seeking) {
          this._audio.currentTime = videoEl.currentTime;
          this.currentTime = videoEl.currentTime;
        }
      });
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
        this.cacheTotalSize = data.total_size || 0;
      } catch {
        /* 后端不可达静默 */
      }
    },

    /** 清空全部本地缓存 */
    async clearAllCache() {
      await clearCache().catch(() => {});
      await this.refreshCacheStatus();
    },

    /** 遍历缓存:每首只保留最高档(开启「清理旧档」设置时立即执行) */
    async cleanupAllCache() {
      await cleanupCache().catch(() => {});
      await this.refreshCacheStatus();
    },

    /** 加载应用设置(后端 data/settings.json 持久化) */
    async loadSettings() {
      try {
        this.settings = await getSettings();
      } catch {
        /* 后端不可达:保持默认 */
      }
    },

    /** 保存设置(合并更新) */
    async saveSetting(patch) {
      try {
        this.settings = await saveSettings(patch);
      } catch {
        /* 静默 */
      }
    },

    /** 入队下载并立即同步状态:乐观标记 checking(检查中),再拉真实状态 */
    async _queueCache(ids, options = {}) {
      await queueCache(ids, options).catch(() => {});
      for (const id of ids) {
        this.cacheStatus[id] = {
          ...(this.cacheStatus[id] || {}),
          state: "checking",
          local_qualities: this.cacheStatus[id]?.local_qualities || [],
        };
      }
      await this.refreshCacheStatus();
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
      // 点击正在播放的曲目:不打断播放
      if (index === this.currentIndex && this.resolved) {
        return;
      }
      // 点播优先由后端处理:plan 接口调用即提队首
      if (record && this.currentIndex >= 0 && index !== this.currentIndex) {
        this._history.push(this.currentIndex); // 记住来的地方
        if (this._history.length > 10000) this._history.shift();
      }
      this.currentIndex = index;
      this.resolved = null;
      this.playing = false;
      this.mvReady = false;
      // 注意:mvEnabled 是「模式」,跨曲目保持,不在切歌时重置
      this.error = "";
      this._loading = true;
      try {
        // 后端决策:plan 接口一次给出档位列表 + 播放来源 + 补缓存决策,
        // 前端无需感知本地/在线
        const plan = await trackPlan(track.id, {
          audioQuality: this.qualityId,
          videoQuality: this.videoQualityId,
        });
        if (this.currentIndex !== index) return; // 用户已切歌,丢弃过期结果
        this.resolved = {
          id: plan.track.id,
          title: plan.track.title,
          artist: plan.track.artist,
          cover: plan.track.cover,
          duration: plan.track.duration,
          source: plan.track.source,
          audio_streams: plan.audio_streams,
          video_streams: plan.video_streams,
        };
        this._applyQualityId();
        this._applyVideoQualityId();
        this._loadStream();
        await this._audio.play();
        // MV 模式开启时,播到视频曲目自动续画面(模式跨曲目保持)
        if (this.mvEnabled) await this._startMv(track);
        // 按后端补缓存决策触发下载(音频+视频合并为一次入队:
        // 分两次入队时第二次会被「已入队跳过」,导致视频补下丢失)
        if (plan.download?.audio != null || plan.download?.video != null) {
          this._queueCache([track.id], {
            priority: true,
            force: true,
            desired_audio: plan.download.audio ?? -2,
            desired_video: plan.download.video ?? -2,
          });
        }
      } catch (e) {
        this.error = `解析失败: ${e.message}`;
      } finally {
        this._loading = false;
      }
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
      this._audio.src = playUrl(this.currentTrack.id, "audio", stream.quality_id);
      this._audio.loop = this.mode === "single-loop";
      this.currentTime = 0;
      this._teardownMv(false); // 只清理画面元素,保持 MV 模式状态
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

    /** 切换音质(保持进度续播,不打断 MV 画面);记住期望音质,跨曲目生效。
     *  选中的档位本地未缓存时,自动后台补下该档。 */
    async setQuality(i) {
      const stream = this.resolved?.audio_streams?.[i];
      if (!stream) return;
      const t = this._audio?.currentTime ?? 0;
      const wasPlaying = this.playing;
      this.qualityIndex = i;
      this.qualityId = stream.quality_id; // 记住期望档,决定后续曲目走本地还是远程
      // 只换音频源,画面独立不受影响(统一端点,后端路由本地/在线)
      this._audio.src = playUrl(this.currentTrack.id, "audio", stream.quality_id);
      this._audio.loop = this.mode === "single-loop";
      this._audio.currentTime = t;
      if (wasPlaying) await this._audio?.play();
      // 切档后重拉 plan:补缓存决策由后端给出
      this._syncPlanDownload();
    },

    /** 按当前期望档重拉 plan,同步档位列表与补缓存决策(切档/登录后调用) */
    async _syncPlanDownload() {
      const track = this.currentTrack;
      if (!track || !this.resolved) return;
      try {
        const plan = await trackPlan(track.id, {
          audioQuality: this.qualityId,
          videoQuality: this.videoQualityId,
        });
        if (this.currentTrack?.id !== track.id) return; // 期间已切歌
        this.resolved.audio_streams = plan.audio_streams;
        this.resolved.video_streams = plan.video_streams;
        this._applyQualityId();
        this._applyVideoQualityId();
        if (plan.download?.audio != null || plan.download?.video != null) {
          this._queueCache([track.id], {
            priority: true,
            force: true,
            desired_audio: plan.download.audio ?? -2,
            desired_video: plan.download.video ?? -2,
          });
        }
      } catch {
        /* 静默 */
      }
    },

    // -------------------------------------------------- MV 模式
    /** MV 模式开关:开启后本次播放及后续播放都保持带画面。
     *  音频区曲目无画面但模式保留,播到视频曲目时自动出现画面。 */
    async toggleMv() {
      if (!this._video) return;
      this.mvEnabled = !this.mvEnabled;
      if (this.mvEnabled) {
        await this._startMv(this.currentTrack);
      } else {
        this._teardownMv();
      }
    },

    /** 为当前曲目启动画面(模式已开启时调用)。无视频流则懒解析远程并补下缓存。 */
    async _startMv(track) {
      if (!track || !this._video) return;
      if (!(this.resolved?.video_streams || []).length) {
        try {
          const plan = await trackPlan(track.id, {
            audioQuality: this.qualityId,
            videoQuality: this.videoQualityId,
          });
          if (this.currentTrack?.id !== track.id) return; // 期间已切歌
          this.resolved.video_streams = plan.video_streams;
          if (!this.resolved.video_streams.length) return; // 该视频无画面,静默
          this._applyVideoQualityId();
          if (plan.download?.video != null) {
            this._queueCache([track.id], {
              priority: true,
              force: true,
              desired_audio: -2,
              desired_video: plan.download.video,
            }); // 补下视频缓存
          }
        } catch (e) {
          this.error = `MV 解析失败: ${e.message}`;
          return;
        }
      }
      const stream = this.currentVideoStream;
      if (!stream) return;
      // 画面走视频流,声音统一由 audio 元素输出(统一端点,后端路由来源)
      this._video.src = playUrl(track.id, "video", stream.quality_id);
      this._video.muted = true;
      this._video.currentTime = this._audio?.currentTime ?? 0;
      if (this.playing) await this._video.play();
      this._startSync();
    },

    /** 切换画质(MV 开启时保持进度续播);选中远程档自动后台补下该画质档 */
    async setVideoQuality(i) {
      const stream = this.resolved?.video_streams?.[i];
      if (!stream) return;
      this.videoIndex = i;
      this.videoQualityId = stream.quality_id; // 记住期望画质,跨曲目生效
      if (this.mvEnabled && this._video) {
        const t = this._video.currentTime;
        const wasPlaying = !this._video.paused;
        this._video.src = playUrl(this.currentTrack.id, "video", stream.quality_id);
        this._video.currentTime = t;
        if (wasPlaying) await this._video.play();
      }
      // 切档后重拉 plan:补缓存决策由后端给出
      this._syncPlanDownload();
    },

    _startSync() {
      clearInterval(this._syncTimer);
      this._syncTimer = setInterval(() => {
        const v = this._video;
        if (!v || !this.mvEnabled || !v.src) return;
        const drift = v.currentTime - (this._audio?.currentTime ?? 0);
        // 画面落后音频过多且正在播放时校正(暂停时不动,尊重用户操作)
        if (drift < -0.8 && !v.seeking && !v.paused) {
          v.currentTime = this._audio.currentTime;
        }
      }, 1500);
    },

    /** 清理画面元素。resetMode=true 时同时关闭 MV 模式(用户手动关闭)。 */
    _teardownMv(resetMode = true) {
      if (resetMode) this.mvEnabled = false;
      this.mvReady = false;
      this._tearingDown = true;
      clearInterval(this._syncTimer);
      if (this._video) {
        this._video.pause();
        this._video.removeAttribute("src");
        this._video.load();
      }
      this._tearingDown = false;
    },

    /** 单曲失败后手动重试下载(插队优先) */
    async retryDownload(trackId) {
      await this._queueCache([trackId], { priority: true });
      this.cacheStatus[trackId] = {
        ...(this.cacheStatus[trackId] || {}),
        state: "pending",
      };
    },

    /** 策略 B:手动下载全部,按期望档位(-1=最高;曲目无该档自动降级)。
     *  按下后列表状态保持不动,后端并发快速检查,检查完成后一次刷新:
     *  需要下载的显示下载中/待下载,其余保持绿勾。 */
    async downloadAll(desiredAudio = -1, desiredVideo = -1) {
      const ids = this.playlist.map((t) => t.id);
      if (!ids.length) return;
      await queueCache(ids, {
        force: true,
        desired_audio: desiredAudio,
        desired_video: desiredVideo,
      }).catch(() => {});
      await this._pollUntilChecked();
    },

    /** 检查阶段快速轮询(1s),全部离开 checking 后停(恢复常规 2s 轮询) */
    async _pollUntilChecked() {
      for (let i = 0; i < 180; i++) {
        await this.refreshCacheStatus();
        const hasChecking = Object.values(this.cacheStatus).some(
          (s) => s.state === "checking"
        );
        if (!hasChecking) return;
        await new Promise((r) => setTimeout(r, 1000));
      }
    },

    /** 登录/登出后刷新当前曲目的档位与补缓存决策(凭证已热更新)。 */
    async refreshResolvedStreams() {
      await this._syncPlanDownload();
    },

    /** 删除单曲本地缓存 */
    async removeCache(trackId) {
      await deleteCacheTrack(trackId).catch(() => {});
      await this.refreshCacheStatus();
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
