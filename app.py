import os
import re
import json
import time
import hmac
import base64
import hashlib
import threading
import unicodedata
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, Response, send_from_directory
import requests

app = Flask(__name__, static_folder=None)

# ==============================================================================
# CẤU HÌNH BẢO MẬT & UPSTREAM API (ẨN HOÀN TOÀN KHỎI CLIENT / NETWORK LOGS)
# ==============================================================================
APP_SECRET = os.environ.get("APP_SECRET", "DVK3010_VKHANH_VIP_QUANTUM_2026_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "9039627841:AAH9WPU5Xu_z6TbmHyojYc7EUjZ_7r_1DkY"
).strip()
ADMIN_CHAT_ID_ENV = os.environ.get("ADMIN_CHAT_ID", "").strip()

MD5_PREDICT_API = os.environ.get("MD5_API_URL", "https://apilc79vip-j6jb.onrender.com/api/md5").strip()
TX_PREDICT_API = os.environ.get("TX_API_URL", "https://apilc79vip-j6jb.onrender.com/api/tx").strip()

KEY_VERIFY_API = os.environ.get("KEY_VERIFY_URL", "https://rivenxvkhanh.onrender.com/api/verify").strip()
KEY_DEVICE_API = os.environ.get("KEY_DEVICE_URL", "https://rivenxvkhanh.onrender.com/api/check-device").strip()

LC79_LOGIN_URL = "https://apifo88daigia.tele68.com/api"
LC79_LOBBY_URL = "https://wlb.tele68.com/v1/lobby/auth/login"
LC79_BAL_URL = "https://gameapi.tele68.com/v1/profile/balance"
LC79_MD5_BASE = "https://wtxmd52.tele68.com/v1/txmd5"
LC79_MD5_LITE = "https://wtxmd52.tele68.com/v1/txmd5/lite-sessions?cp=R&cl=R&pf=web&at=405f18b5220fdd5674e8bb74bd0d5d14"
LC79_TX_URL = "https://wtx.tele68.com/v1/tx/sessions"

RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
STATE_FILE = "state_data.json"
VN_TZ = timezone(timedelta(hours=7))

state_lock = threading.RLock()
HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
})


def vn_now_str():
    return datetime.now(VN_TZ).strftime("%H:%M:%S")


def vn_full_str():
    return datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")


def strip_accents_upper(val):
    if val is None:
        return ""
    s = str(val).strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.upper()


def normalize_side(raw, total=None):
    if raw is not None:
        s = strip_accents_upper(raw)
        if any(k in s for k in ("TAI", "BIG", "OVER")) or s == "T":
            return "T"
        if any(k in s for k in ("XIU", "SMALL", "UNDER")) or s == "X":
            return "X"
        try:
            n = int(float(s))
            if 3 <= n <= 18:
                return "T" if n >= 11 else "X"
        except Exception:
            pass
    if isinstance(total, (int, float)) and 3 <= int(total) <= 18:
        return "T" if int(total) >= 11 else "X"
    return None


def parse_session_int(raw):
    if raw is None or isinstance(raw, (dict, list, bool)):
        return None
    s = re.sub(r"[^\d]", "", str(raw))
    if not s:
        return None
    try:
        val = int(s)
        return val if val > 0 else None
    except Exception:
        return None


def parse_confidence(raw):
    if raw is None or isinstance(raw, (dict, list, bool)):
        return None
    s = str(raw).replace("%", "").strip()
    try:
        val = float(s)
        if 0 < val <= 1.0:
            val = val * 100.0
        val = max(0.0, min(100.0, val))
        return round(val, 1) if val % 1 != 0 else int(val)
    except Exception:
        return None


def parse_strict_money(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return int(round(raw))
    cleaned = re.sub(r"[^\d-]", "", str(raw))
    if not cleaned or cleaned == "-":
        return None
    try:
        return int(cleaned)
    except Exception:
        return None


# ==============================================================================
# MÃ HÓA ENVELOPE CHO GIAO TIẾP CLIENT <-> SERVER (ẨN DỮ LIỆU NETWORK LOG)
# ==============================================================================
def xor_crypt_bytes(data_bytes: bytes, key_str: str) -> bytes:
    k = hashlib.sha256(key_str.encode("utf-8")).digest()
    out = bytearray(len(data_bytes))
    klen = len(k)
    for i, b in enumerate(data_bytes):
        out[i] = b ^ k[i % klen]
    return bytes(out)


def encode_envelope(payload_obj, ts_str: str) -> str:
    raw = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    xored = xor_crypt_bytes(raw, f"{APP_SECRET}:{ts_str}")
    return base64.b64encode(xored).decode("ascii")


def decode_envelope(encoded_str: str, ts_str: str):
    if not encoded_str:
        return {}
    raw_xored = base64.b64decode(encoded_str.encode("ascii"))
    raw = xor_crypt_bytes(raw_xored, f"{APP_SECRET}:{ts_str}")
    return json.loads(raw.decode("utf-8"))


def verify_client_sig():
    ts = request.headers.get("X-Ts", "")
    sig = request.headers.get("X-Sig", "")
    if not ts or not sig:
        return False, "0"
    expected = hmac.new(
        APP_SECRET.encode("utf-8"),
        f"{ts}:{request.path}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:24]
    if not hmac.compare_digest(sig, expected):
        return False, ts
    return True, ts


def secure_json_response(data_obj, status_code=200):
    ts = str(int(time.time() * 1000))
    resp = jsonify({"t": ts, "p": encode_envelope(data_obj, ts)})
    resp.status_code = status_code
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


def read_secure_request():
    ok, ts = verify_client_sig()
    if not ok:
        return None, None
    body = request.get_json(silent=True) or {}
    if "p" in body and "t" in body:
        try:
            decoded = decode_envelope(body["p"], str(body["t"]))
            return decoded, str(body["t"])
        except Exception:
            return None, ts
    return body, ts


# ==============================================================================
# TRẠNG THÁI TOÀN CỤC & LƯU TRỮ BỀN VỮNG 24/24
# ==============================================================================
def make_stream_state():
    return {
        "currentSession": None,
        "nextSession": None,
        "prediction": None,      # "T" | "X" | None
        "predictionText": "--",  # "TÀI" | "XỈU" | "--"
        "confidence": 0,
        "apiOnline": False,
        "lastUpdate": 0,
        "wins": 0,
        "losses": 0,
        "currentWinStreak": 0,
        "currentLossStreak": 0,
        "maxWinStreak": 0,
        "maxLossStreak": 0,
        "history": [],           # list of {id, actual, dice, sum} newest first
        "preds": {},             # session_str -> {prediction: "TÀI"|"XỈU", confidence: num}
        "settledSessions": []    # list of session ints already counted for W/L streaks
    }


def make_autobet_state():
    return {
        "isRunning": False,
        "username": "",
        "password": "",
        "rawCapitalInput": 0,
        "capital": 0,
        "totalLossAmount": 0,
        "initialBalance": 0,
        "balance": 0,
        "realAccountBalance": 0,
        "targetProfit": 0,
        "maxLosses": 3,
        "betAmount": 1000,
        "betMode": "safe",
        "wins": 0,
        "losses": 0,
        "consecutiveLosses": 0,
        "consecutiveWins": 0,
        "maxWinStreak": 0,
        "maxLossStreak": 0,
        "lossStopCounter": 0,
        "netProfit": 0,
        "currentSessionId": None,
        "nextSessionId": None,
        "initialSessionId": None,
        "lastBetSession": None,
        "lastBetSide": None,
        "lastBetAmount": 0,
        "lastProcessedSession": None,
        "lastSkippedSession": None,
        "preBetBalance": 0,
        "lastApiPostBalance": 0,
        "consecutiveBetErrors": 0,
        "placedSessions": [],
        "statusHeadline": "Chưa khởi chạy Auto Cược",
        "statusDetail": "Hoàn tất Đăng Nhập (Tab 1) và Cài Đặt (Tab 2), sau đó nhấn Bắt Đầu.",
        "statusStage": "idle",
        "summaryReason": "",
        "lastActivityTs": int(time.time() * 1000),
        "lastHeartbeatTs": int(time.time() * 1000),
        "logs": []
    }


SYSTEM_STATE = {
    "webStatus": "ACTIVE",  # ACTIVE | LOCKED | MAINTENANCE | DISABLED
    "statusMessage": "",
    "announcement": "",
    "adminIds": [],
    "pendingAdminAction": {},  # chat_id_str -> action_name
    "streams": {
        "md5": make_stream_state(),
        "tx": make_stream_state()
    },
    "autobet": make_autobet_state()
}


def load_persisted_state():
    if ADMIN_CHAT_ID_ENV:
        for cid in ADMIN_CHAT_ID_ENV.split(","):
            cid = cid.strip()
            if cid.isdigit() and int(cid) not in SYSTEM_STATE["adminIds"]:
                SYSTEM_STATE["adminIds"].append(int(cid))
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return
        if raw.get("webStatus") in ("ACTIVE", "LOCKED", "MAINTENANCE", "DISABLED"):
            SYSTEM_STATE["webStatus"] = raw["webStatus"]
        SYSTEM_STATE["statusMessage"] = str(raw.get("statusMessage", ""))
        SYSTEM_STATE["announcement"] = str(raw.get("announcement", ""))
        for aid in raw.get("adminIds", []):
            if isinstance(aid, int) and aid not in SYSTEM_STATE["adminIds"]:
                SYSTEM_STATE["adminIds"].append(aid)
        for sk in ("md5", "tx"):
            if isinstance(raw.get("streams", {}).get(sk), dict):
                SYSTEM_STATE["streams"][sk].update(raw["streams"][sk])
        if isinstance(raw.get("autobet"), dict):
            SYSTEM_STATE["autobet"].update(raw["autobet"])
    except Exception:
        pass


def save_persisted_state():
    with state_lock:
        try:
            payload = {
                "webStatus": SYSTEM_STATE["webStatus"],
                "statusMessage": SYSTEM_STATE["statusMessage"],
                "announcement": SYSTEM_STATE["announcement"],
                "adminIds": SYSTEM_STATE["adminIds"],
                "streams": {
                    "md5": {
                        **SYSTEM_STATE["streams"]["md5"],
                        "history": SYSTEM_STATE["streams"]["md5"]["history"][:80],
                        "settledSessions": SYSTEM_STATE["streams"]["md5"]["settledSessions"][-200:],
                        "preds": dict(list(SYSTEM_STATE["streams"]["md5"]["preds"].items())[-120:])
                    },
                    "tx": {
                        **SYSTEM_STATE["streams"]["tx"],
                        "history": SYSTEM_STATE["streams"]["tx"]["history"][:80],
                        "settledSessions": SYSTEM_STATE["streams"]["tx"]["settledSessions"][-200:],
                        "preds": dict(list(SYSTEM_STATE["streams"]["tx"]["preds"].items())[-120:])
                    }
                },
                "autobet": {
                    **SYSTEM_STATE["autobet"],
                    "logs": SYSTEM_STATE["autobet"]["logs"][:80],
                    "placedSessions": SYSTEM_STATE["autobet"]["placedSessions"][-120:]
                }
            }
            tmp_file = STATE_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_file, STATE_FILE)
        except Exception:
            pass


load_persisted_state()


# ==============================================================================
# PARSER API DỰ ĐOÁN (CHỈ LẤY DỰ ĐOÁN, ĐỘ TIN CẬY, PHIÊN TỪ API)
# ==============================================================================
def extract_prediction_payload(payload):
    if not payload or not isinstance(payload, dict):
        return None
    candidates = [payload]
    for sub_k in ("data", "result", "prediction_data", "info"):
        if isinstance(payload.get(sub_k), dict):
            candidates.append(payload[sub_k])

    pred_side = None
    conf_val = None
    pred_session = None

    pred_keys = (
        "du_doan", "dudoan", "duDoan", "prediction", "pred",
        "ket_qua_du_doan", "ketQuaDuDoan", "side", "pick",
        "choice", "tx", "ketqua", "ket_qua", "result"
    )
    conf_keys = (
        "do_tin_cay", "dotincay", "doTinCay", "confidence", "conf",
        "ti_le", "tile", "tiLe", "ty_le", "tyle", "percent",
        "percentage", "prob", "probability", "win_rate", "accuracy", "score"
    )
    sess_keys = (
        "phien_du_doan", "phienDuDoan", "next_phien", "nextPhien",
        "next_session", "nextSession", "target_session", "targetSession",
        "phien", "session", "session_id", "sessionId", "id", "issue", "period", "round"
    )

    for obj in candidates:
        if pred_side is None:
            for k in pred_keys:
                if k in obj and obj[k] is not None:
                    s = normalize_side(obj[k])
                    if s in ("T", "X"):
                        pred_side = s
                        break
        if conf_val is None:
            for k in conf_keys:
                if k in obj and obj[k] is not None:
                    c = parse_confidence(obj[k])
                    if c is not None:
                        conf_val = c
                        break
        if pred_session is None:
            for k in sess_keys:
                if k in obj and obj[k] is not None:
                    sid = parse_session_int(obj[k])
                    if sid is not None:
                        pred_session = sid
                        break

    if pred_side is None and pred_session is None:
        return None

    return {
        "side": pred_side,
        "predictionText": "TÀI" if pred_side == "T" else ("XỈU" if pred_side == "X" else "--"),
        "confidence": conf_val if conf_val is not None else 0,
        "session": pred_session
    }


def parse_lc79_history(payload):
    raw_list = None
    if isinstance(payload, list):
        raw_list = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("list"), list):
            raw_list = payload["list"]
        elif isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("list"), list):
            raw_list = payload["data"]["list"]
        elif isinstance(payload.get("data"), list):
            raw_list = payload["data"]
    if not raw_list:
        return []

    rounds_by_id = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        sid = parse_session_int(
            item.get("id") or item.get("issue") or item.get("sessionId")
            or item.get("roundId") or item.get("period") or item.get("phien")
        )
        if not sid:
            continue
        raw_dice = item.get("dices") or item.get("dice") or item.get("diceList") or item.get("openCode") or []
        dice = []
        if isinstance(raw_dice, str):
            parts = [p for p in re.split(r"[\s,;|:-]+", raw_dice.strip()) if p.isdigit()]
            dice = [int(x) for x in parts[:3]]
        elif isinstance(raw_dice, list):
            try:
                dice = [int(x) for x in raw_dice[:3]]
            except Exception:
                dice = []
        if len(dice) != 3 or not all(1 <= d <= 6 for d in dice):
            dice = []

        dice_sum = sum(dice) if len(dice) == 3 else None
        raw_sum = item.get("sum") or item.get("total") or item.get("diceSum") or item.get("point")
        sup_sum = None
        if raw_sum is not None:
            try:
                n = int(float(str(raw_sum)))
                if 3 <= n <= 18:
                    sup_sum = n
            except Exception:
                pass
        total_pt = dice_sum if dice_sum is not None else sup_sum
        actual = normalize_side(
            item.get("resultTruyenThong") or item.get("result") or item.get("outcome") or item.get("openResult"),
            total_pt
        )
        if actual not in ("T", "X"):
            continue
        rounds_by_id[sid] = {
            "id": str(sid),
            "session": sid,
            "actual": "TAI" if actual == "T" else "XIU",
            "tx": actual,
            "dice": dice,
            "sum": total_pt
        }

    sorted_rounds = sorted(rounds_by_id.values(), key=lambda r: r["session"], reverse=True)
    return sorted_rounds[:120]


def fetch_upstream_prediction(stream_key):
    url = MD5_PREDICT_API if stream_key == "md5" else TX_PREDICT_API
    try:
        res = HTTP.get(url, timeout=12)
        if res.ok:
            data = res.json()
            if isinstance(data, str):
                data = json.loads(data)
            parsed = extract_prediction_payload(data)
            if parsed:
                return parsed
    except Exception:
        pass
    return None


def fetch_upstream_history(stream_key):
    urls = [LC79_MD5_LITE, f"{LC79_MD5_BASE}/sessions?cp=R&cl=R&pf=web&at="] if stream_key == "md5" else [LC79_TX_URL]
    for url in urls:
        try:
            res = HTTP.get(url, timeout=8)
            if res.ok:
                data = res.json()
                if isinstance(data, str):
                    data = json.loads(data)
                rows = parse_lc79_history(data)
                if rows:
                    return rows
        except Exception:
            pass
    return []


def update_stream_cycle(stream_key):
    pred_data = fetch_upstream_prediction(stream_key)
    hist_rows = fetch_upstream_history(stream_key)

    with state_lock:
        st = SYSTEM_STATE["streams"][stream_key]
        changed = False

        if hist_rows:
            existing = {r["id"]: r for r in st["history"]}
            for r in hist_rows:
                existing[r["id"]] = r
            merged_desc = sorted(existing.values(), key=lambda x: int(x["session"]), reverse=True)[:120]
            st["history"] = merged_desc
            latest_completed = int(merged_desc[0]["session"])
            if st["currentSession"] != latest_completed:
                st["currentSession"] = latest_completed
                changed = True

        if pred_data:
            st["apiOnline"] = True
            st["lastUpdate"] = int(time.time() * 1000)
            api_sess = pred_data.get("session")
            cur_sess = st["currentSession"]

            if api_sess is not None:
                # Nếu API trả phiên hiện tại bằng phiên đã xong thì phiên dự đoán là api_sess + 1, ngược lại lấy đúng api_sess
                if cur_sess is not None and api_sess == cur_sess:
                    target_sess = api_sess + 1
                else:
                    target_sess = api_sess
            else:
                target_sess = (cur_sess + 1) if cur_sess is not None else None

            if target_sess is not None and st["nextSession"] != target_sess:
                st["nextSession"] = target_sess
                changed = True

            if pred_data.get("side") in ("T", "X"):
                if st["prediction"] != pred_data["side"] or st["confidence"] != pred_data["confidence"]:
                    st["prediction"] = pred_data["side"]
                    st["predictionText"] = pred_data["predictionText"]
                    st["confidence"] = pred_data["confidence"]
                    changed = True

                if target_sess is not None:
                    st["preds"][str(target_sess)] = {
                        "prediction": pred_data["predictionText"],
                        "confidence": pred_data["confidence"]
                    }
        else:
            if int(time.time() * 1000) - st["lastUpdate"] > 25000:
                st["apiOnline"] = False

        # Đối soát thắng / thua & chuỗi thắng / thua cao nhất (tự tính logic chuẩn xác)
        settled_set = set(st["settledSessions"])
        hist_asc = sorted(st["history"], key=lambda x: int(x["session"]))
        for r in hist_asc:
            sid = int(r["session"])
            if sid in settled_set:
                continue
            p_rec = st["preds"].get(str(sid))
            if not p_rec:
                continue
            pred_tx = "T" if p_rec.get("prediction") == "TÀI" else ("X" if p_rec.get("prediction") == "XỈU" else None)
            if pred_tx not in ("T", "X"):
                continue

            settled_set.add(sid)
            st["settledSessions"].append(sid)
            changed = True

            if pred_tx == r["tx"]:
                st["wins"] += 1
                st["currentWinStreak"] += 1
                st["currentLossStreak"] = 0
                if st["currentWinStreak"] > st["maxWinStreak"]:
                    st["maxWinStreak"] = st["currentWinStreak"]
            else:
                st["losses"] += 1
                st["currentLossStreak"] += 1
                st["currentWinStreak"] = 0
                if st["currentLossStreak"] > st["maxLossStreak"]:
                    st["maxLossStreak"] = st["currentLossStreak"]

        if changed:
            save_persisted_state()


# ==============================================================================
# XÁC MINH KEY VIP LIÊN TỤC (rivenxvkhanh.onrender.com)
# ==============================================================================
def _post_key_json(url, payload, timeout=18):
    last_err = ""
    for attempt in range(2):
        try:
            res = HTTP.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=timeout + (attempt * 4)
            )
            if res.status_code in (502, 503, 504) and attempt == 0:
                time.sleep(0.8)
                continue
            text = res.text
            try:
                data = res.json()
                if isinstance(data, str):
                    data = json.loads(data)
            except Exception:
                data = {"_raw_text": text}
            return res.status_code, data
        except Exception as e:
            last_err = str(e)
            if attempt == 0:
                time.sleep(0.8)
    return 0, {"_network_error": last_err}


def _unwrap_key_payload(data):
    if not isinstance(data, dict):
        return {}
    merged = dict(data)
    for sub_k in ("data", "result", "key_info", "license", "device"):
        sub = data.get(sub_k)
        if isinstance(sub, dict):
            merged = {**sub, **merged}
    return merged


def _format_key_expiry(merged):
    if not isinstance(merged, dict):
        return ""
    for exp_k in (
        "expiresAt", "expires_at", "expire_at", "expired_at",
        "expiry", "expires", "expireDate", "expire_date",
        "han_su_dung", "valid_until", "end_date"
    ):
        val = merged.get(exp_k)
        if val is not None and str(val).strip() != "":
            if isinstance(val, (int, float)):
                ts = val / 1000.0 if val > 1e11 else float(val)
                if ts > 1600000000:
                    dt = datetime.fromtimestamp(ts, tz=VN_TZ)
                    return f"HSD: {dt.strftime('%d/%m/%Y %H:%M')}"
            s = str(val).strip()
            try:
                iso_s = s.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso_s)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(VN_TZ)
                return f"HSD: {dt.strftime('%d/%m/%Y %H:%M')}"
            except Exception:
                pass
            if s.upper().startswith(("HSD", "CÒN", "CON ")):
                return s
            return f"HSD: {s}"

    for day_k in ("days_left", "remaining_days", "days", "duration_days", "so_ngay"):
        val = merged.get(day_k)
        if val is not None and str(val).strip() != "":
            s = str(val).strip()
            return s if ("NGÀY" in s.upper() or "NGAY" in s.upper()) else f"Còn {s} ngày"

    return ""


def _humanize_key_error(status_code, merged):
    if not isinstance(merged, dict):
        return "Không thể kết nối máy chủ xác minh Key. Vui lòng thử lại sau giây lát!"
    if "_network_error" in merged or status_code == 0 or (isinstance(status_code, int) and status_code >= 500):
        return "Không thể kết nối máy chủ xác minh Key. Vui lòng kiểm tra mạng và thử lại sau giây lát!"

    raw_parts = [
        merged.get("message"), merged.get("msg"), merged.get("detail"),
        merged.get("error"), merged.get("reason"), merged.get("status"),
        merged.get("state"), merged.get("code"), merged.get("_raw_text")
    ]
    combined_upper = strip_accents_upper(" ".join(str(p) for p in raw_parts if p is not None))

    # 1. Key hết hạn
    if (
        merged.get("expired") is True
        or merged.get("isExpired") is True
        or status_code == 410
        or any(k in combined_upper for k in ("EXPIRE", "HET HAN", "OUT OF DATE", "OVERDUE"))
    ):
        return "Mã Key của bạn đã hết hạn sử dụng. Vui lòng gia hạn hoặc nhập Key mới!"

    # 2. Key bị khóa / vô hiệu hóa / thu hồi
    if (
        merged.get("locked") is True
        or merged.get("isLocked") is True
        or merged.get("banned") is True
        or merged.get("disabled") is True
        or merged.get("revoked") is True
        or any(k in combined_upper for k in ("LOCK", "BAN", "BLOCK", "REVOKE", "DISABLE", "SUSPEND", "KHOA", "VO HIEU"))
    ):
        return "Mã Key của bạn đã bị khóa hoặc vô hiệu hóa. Vui lòng liên hệ Admin để được hỗ trợ!"

    # 3. Sai thiết bị / HWID đã kích hoạt trên máy khác
    if (
        merged.get("hwid_mismatch") is True
        or merged.get("device_mismatch") is True
        or any(k in combined_upper for k in (
            "HWID", "DEVICE", "THIET BI", "ANOTHER", "OTHER",
            "ALREADY USED", "BOUND", "MAX_DEVICE", "DEVICE LIMIT"
        ))
    ):
        return "Mã Key này đã được kích hoạt trên thiết bị khác. Mỗi Key chỉ dùng được cho 1 thiết bị!"

    # 4. Key sai / không tồn tại / không hợp lệ
    if (
        status_code in (400, 401, 403, 404, 422)
        or any(k in combined_upper for k in (
            "NOT FOUND", "NOT_FOUND", "INVALID", "WRONG", "NOT EXIST",
            "DOES NOT EXIST", "SAI KEY", "KHONG TON TAI", "KHONG HOP LE", "KHONG DUNG"
        ))
    ):
        return "Mã Key không đúng hoặc không tồn tại. Vui lòng kiểm tra lại!"

    return "Mã Key không hợp lệ hoặc không thể sử dụng. Vui lòng kiểm tra lại hoặc liên hệ Admin!"


def evaluate_verify_response(status_code, data, key_str=""):
    if not isinstance(data, dict):
        return False, "Không thể kết nối máy chủ xác minh Key. Vui lòng thử lại sau giây lát!", ""
    if "_network_error" in data or status_code == 0 or status_code >= 500:
        return None, _humanize_key_error(status_code, data), ""

    merged = _unwrap_key_payload(data)
    exp = _format_key_expiry(merged)

    status_str = strip_accents_upper(merged.get("status") or merged.get("state") or "")
    msg_upper = strip_accents_upper(
        merged.get("message") or merged.get("msg") or merged.get("detail")
        or merged.get("error") or merged.get("reason") or ""
    )

    # Kiểm tra trước các dấu hiệu bị khóa / hết hạn / sai thiết bị / sai key
    if (
        merged.get("locked") is True or merged.get("isLocked") is True
        or merged.get("banned") is True or merged.get("disabled") is True
        or merged.get("revoked") is True or merged.get("expired") is True
        or merged.get("isExpired") is True
        or merged.get("hwid_mismatch") is True or merged.get("device_mismatch") is True
    ):
        return False, _humanize_key_error(status_code, merged), exp

    if status_str in (
        "INVALID", "EXPIRED", "LOCKED", "BANNED", "DISABLED",
        "REVOKED", "ERROR", "FAIL", "FAILED", "FALSE", "NOT_FOUND", "MISMATCH"
    ):
        return False, _humanize_key_error(status_code, merged), exp

    if any(k in msg_upper for k in (
        "EXPIRE", "HET HAN", "LOCK", "BAN", "BLOCK", "REVOKE", "DISABLE",
        "KHOA", "VO HIEU", "INVALID", "NOT FOUND", "NOT_FOUND",
        "DOES NOT EXIST", "KHONG TON TAI", "KHONG HOP LE", "SAI KEY",
        "WRONG", "MISMATCH", "THIET BI KHAC", "ANOTHER DEVICE"
    )):
        return False, _humanize_key_error(status_code, merged), exp

    # Kiểm tra các cờ xác nhận hợp lệ (boolean, số hoặc chuỗi)
    for flag_k in ("valid", "success", "ok", "isValid", "is_valid", "verified", "active", "activated", "authorized"):
        if flag_k in merged:
            val = merged[flag_k]
            if isinstance(val, bool):
                if val:
                    return True, "Xác minh Key VIP thành công!", exp
                return False, _humanize_key_error(status_code, merged), exp
            if isinstance(val, (int, float)) and val in (0, 1):
                if val == 1:
                    return True, "Xác minh Key VIP thành công!", exp
                return False, _humanize_key_error(status_code, merged), exp
            if isinstance(val, str):
                v_low = val.strip().lower()
                if v_low in ("true", "1", "yes", "valid", "ok", "success"):
                    return True, "Xác minh Key VIP thành công!", exp
                if v_low in ("false", "0", "no", "invalid", "fail", "failed"):
                    return False, _humanize_key_error(status_code, merged), exp

    if status_str in ("VALID", "ACTIVE", "OK", "SUCCESS", "VERIFIED", "BOUND", "ACTIVATED", "USED", "VALID_KEY"):
        return True, "Xác minh Key VIP thành công!", exp

    # Trường hợp API trả HTTP 200 kèm thông tin key/hạn dùng mà không có cờ boolean riêng
    if 200 <= status_code < 300 and not merged.get("error"):
        returned_key = str(merged.get("key") or merged.get("license_key") or "").strip()
        if returned_key and key_str and returned_key.upper() != key_str.upper():
            return False, "Mã Key không khớp hoặc không hợp lệ. Vui lòng kiểm tra lại!", exp
        if exp or any(k in merged for k in ("key", "license_key", "hwid", "device_id", "plan", "package", "days_left")):
            return True, "Xác minh Key VIP thành công!", exp

    return False, _humanize_key_error(status_code, merged), exp


def evaluate_device_response(status_code, data, key_str=""):
    if not isinstance(data, dict) or "_network_error" in data or status_code == 0 or status_code >= 500:
        return None, "", ""

    merged = _unwrap_key_payload(data)
    exp = _format_key_expiry(merged)

    status_str = strip_accents_upper(merged.get("status") or merged.get("state") or "")
    msg_upper = strip_accents_upper(
        merged.get("message") or merged.get("msg") or merged.get("detail")
        or merged.get("error") or merged.get("reason") or ""
    )

    if (
        merged.get("expired") is True or merged.get("isExpired") is True
        or "EXPIRE" in status_str or "HET HAN" in msg_upper or "EXPIRE" in msg_upper
    ):
        return False, "Mã Key của bạn đã hết hạn sử dụng. Vui lòng gia hạn hoặc nhập Key mới!", exp

    if (
        merged.get("locked") is True or merged.get("isLocked") is True
        or merged.get("banned") is True or merged.get("disabled") is True
        or any(w in status_str for w in ("LOCK", "BAN", "REVOKE", "DISABLE"))
        or any(w in msg_upper for w in ("LOCK", "BAN", "KHOA", "VO HIEU", "REVOKE"))
    ):
        return False, "Mã Key của bạn đã bị khóa hoặc vô hiệu hóa. Vui lòng liên hệ Admin để được hỗ trợ!", exp

    bound_key = str(merged.get("key") or merged.get("license_key") or "").strip()
    if bound_key and key_str and bound_key.upper() != key_str.upper():
        return False, "Thiết bị này đang liên kết với một mã Key khác. Vui lòng kiểm tra lại!", exp

    if 200 <= status_code < 300:
        for flag_k in ("valid", "success", "ok", "has_key", "hasKey", "bound", "is_bound", "isBound", "registered", "found", "exists", "active", "verified"):
            val = merged.get(flag_k)
            if val is True or val == 1 or (isinstance(val, str) and val.strip().lower() in ("true", "1", "yes")):
                return True, "Xác minh Key VIP thành công!", exp
        if status_str in ("VALID", "ACTIVE", "OK", "SUCCESS", "BOUND", "VERIFIED", "REGISTERED"):
            return True, "Xác minh Key VIP thành công!", exp
        if bound_key and key_str and bound_key.upper() == key_str.upper():
            return True, "Xác minh Key VIP thành công!", exp

    return None, "", exp


def verify_vip_key_full(key_str, device_id, check_device_too=True):
    key_str = str(key_str or "").strip()
    device_id = str(device_id or "").strip()
    if not key_str:
        return {"valid": False, "message": "Vui lòng nhập mã Key VIP để tiếp tục!", "expires": ""}

    # 1. Gọi POST /api/verify đúng cấu trúc {"key": ..., "hwid": ...}
    code1, data1 = _post_key_json(KEY_VERIFY_API, {"key": key_str, "hwid": device_id})
    v1, msg1, exp1 = evaluate_verify_response(code1, data1, key_str)
    if v1 is False:
        return {"valid": False, "message": msg1, "expires": exp1}

    # 2. Gọi POST /api/check-device đúng cấu trúc {"device_id": ...}
    exp2 = ""
    if check_device_too and KEY_DEVICE_API and device_id:
        code2, data2 = _post_key_json(KEY_DEVICE_API, {"device_id": device_id})
        v2, msg2, exp2 = evaluate_device_response(code2, data2, key_str)
        if v2 is False:
            return {"valid": False, "message": msg2, "expires": exp2 or exp1}
        if v1 is True:
            return {"valid": True, "message": msg1 or "Xác minh Key VIP thành công!", "expires": exp1 or exp2}
        if v1 is None and v2 is True:
            return {"valid": True, "message": msg2 or "Xác minh Key VIP thành công!", "expires": exp2 or exp1}

    if v1 is True:
        return {"valid": True, "message": msg1 or "Xác minh Key VIP thành công!", "expires": exp1 or exp2}

    return {
        "valid": False,
        "message": msg1 or "Không thể kết nối máy chủ xác minh Key. Vui lòng kiểm tra mạng và thử lại sau giây lát!",
        "expires": ""
    }

# ==============================================================================
# ENGINE AUTO PHÂN TÍCH • CƯỢC MD5 CHẠY NỀN 24/24 TRÊN SERVER (KỂ CẢ KHI THOÁT WEB)
# ==============================================================================
class ServerLC79AutoClient:
    def __init__(self):
        self.username = ""
        self.password = ""
        self.md5_password = ""
        self.token = None
        self.jwt_token = None
        self.balance = 0
        self.is_logged_in = False

    def login(self, username, password):
        self.username = str(username or "").strip()
        self.password = str(password or "").strip()
        self.md5_password = hashlib.md5(self.password.encode("utf-8")).hexdigest()
        self.token = None
        self.jwt_token = None
        self.is_logged_in = False

        try:
            res1 = HTTP.get(
                LC79_LOGIN_URL,
                params={"c": "3", "un": self.username, "pw": self.md5_password, "cp": "R", "cl": "R", "pf": "web", "at": ""},
                timeout=12
            )
            data1 = res1.json() if res1.ok else {}
            if not data1.get("success"):
                return {"ok": False, "message": "❌ Sai tài khoản hoặc mật khẩu LC79 ảo!", "balance": 0}

            self.token = data1.get("accessToken")
            session_key = data1.get("sessionKey", "")
            nick_name = self.username
            try:
                if session_key:
                    padded = session_key + "=" * ((4 - len(session_key) % 4) % 4)
                    sobj = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
                    if isinstance(sobj, dict) and sobj.get("nickname"):
                        nick_name = sobj["nickname"]
            except Exception:
                pass

            res2 = HTTP.post(
                LC79_LOBBY_URL,
                params={"cp": "R", "cl": "R", "pf": "web", "at": self.token},
                json={
                    "username": self.username,
                    "password": self.md5_password,
                    "nickName": nick_name,
                    "accessToken": self.token,
                    "sessionKey": session_key
                },
                timeout=12
            )
            data2 = res2.json() if res2.ok else {}
            if not data2.get("token"):
                return {"ok": False, "message": "❌ Xác thực Lobby LC79 thất bại!", "balance": 0}

            self.jwt_token = data2["token"]
            remote_resp = data2.get("remoteLoginResp") if isinstance(data2.get("remoteLoginResp"), dict) else {}
            lobby_money = parse_strict_money(
                remote_resp.get("money") if remote_resp.get("money") is not None
                else (remote_resp.get("balance") if remote_resp.get("balance") is not None else data2.get("money"))
            )
            if lobby_money is not None and lobby_money >= 0:
                self.balance = lobby_money
            self.is_logged_in = True

            live_bal = self.fetch_balance_strict()
            if live_bal is not None and live_bal >= 0:
                self.balance = live_bal

            return {"ok": True, "message": "✅ Đăng nhập LC79 ảo thành công!", "balance": self.balance}
        except Exception as e:
            self.is_logged_in = False
            return {"ok": False, "message": f"❌ Lỗi kết nối LC79: {e}", "balance": 0}

    def relogin_if_needed(self):
        if not self.username or not self.password:
            return False
        return self.login(self.username, self.password).get("ok", False)

    def fetch_balance_strict(self):
        if not self.token or not self.jwt_token:
            if not self.relogin_if_needed():
                return None
        for attempt in range(2):
            try:
                res = HTTP.get(
                    LC79_BAL_URL,
                    params={"cp": "R", "cl": "R", "pf": "web", "at": self.token},
                    headers={"Authorization": f"Bearer {self.jwt_token}"},
                    timeout=10
                )
                if res.status_code in (401, 403) and attempt == 0:
                    if self.relogin_if_needed():
                        continue
                    return None
                if res.ok:
                    data = res.json()
                    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
                    raw_bal = (
                        data.get("balance") if data.get("balance") is not None
                        else data.get("money") if data.get("money") is not None
                        else nested.get("balance") if nested.get("balance") is not None
                        else nested.get("money")
                    )
                    parsed = parse_strict_money(raw_bal)
                    if parsed is not None and parsed >= 0:
                        self.balance = parsed
                        return self.balance
            except Exception:
                if attempt == 0 and self.relogin_if_needed():
                    continue
        return None

    def place_bet(self, raw_side, stake, target_session, current_session, allowed_cap):
        if raw_side not in ("T", "X"):
            return {"ok": False, "reason": "invalid_side", "message": "Cửa cược không hợp lệ."}
        stake = int(stake)
        if stake < 1000:
            return {"ok": False, "reason": "invalid_stake", "message": "Cược tối thiểu 1.000đ."}
        if allowed_cap < stake:
            return {"ok": False, "reason": "capital_limit_exceeded", "message": "Vốn cố định còn lại không đủ."}
        if int(target_session) != int(current_session) + 1:
            return {"ok": False, "reason": "invalid_session", "message": "Chặn đặt sai phiên."}

        if self.balance < stake:
            fb = self.fetch_balance_strict()
            if fb is None or fb < stake:
                return {"ok": False, "reason": "insufficient_balance", "message": "Số dư ví không đủ."}

        bet_type = "TAI" if raw_side == "T" else "XIU"
        for attempt in range(2):
            try:
                res = HTTP.post(
                    f"{LC79_MD5_BASE}/bet",
                    params={"limit": "8", "cp": "R", "cl": "R", "pf": "web", "at": self.token},
                    headers={"Authorization": f"Bearer {self.jwt_token}"},
                    json={
                        "username": self.username,
                        "password": self.md5_password,
                        "amount": stake,
                        "side": raw_side,
                        "session": int(target_session),
                        "type": bet_type
                    },
                    timeout=10
                )
                data = res.json() if res.text else {}
                if res.ok and data.get("postBalance") is not None:
                    pre_bal = self.balance
                    post_bal = parse_strict_money(data.get("postBalance"))
                    self.balance = post_bal if post_bal is not None else max(0, pre_bal - stake)
                    res_key = strip_accents_upper(data.get("result") or data.get("ketQua") or "")
                    won = None
                    if res_key in ("T", "TAI"):
                        won = (raw_side == "T")
                    elif res_key in ("X", "XIU"):
                        won = (raw_side == "X")
                    net_change = (round(stake * 1.98) - stake) if won is True else (-stake if won is False else (self.balance - pre_bal))
                    return {
                        "ok": True,
                        "session": int(target_session),
                        "side": raw_side,
                        "betAmount": stake,
                        "postBalance": self.balance,
                        "netChange": net_change,
                        "settledImmediately": won is not None,
                        "won": won
                    }
                msg_low = str(data.get("message") or res.text or "").lower()
                if any(k in msg_low for k in ("out_of_time", "time", "het thoi gian", "dong cuoc", "qua gio")):
                    return {"ok": False, "reason": "out_of_time_exhausted", "message": "Quá thời gian cược phiên hiện tại."}
                if attempt == 0 and (res.status_code in (401, 403) or any(k in msg_low for k in ("token", "auth", "login", "expired"))):
                    if self.relogin_if_needed():
                        continue
                return {"ok": False, "reason": "api_rejected", "message": f"Đặt cược thất bại: {data}"}
            except Exception as e:
                return {"ok": False, "reason": "exception", "message": f"Lỗi đặt cược: {e}"}
        return {"ok": False, "reason": "auth_failed", "message": "Hết hạn đăng nhập LC79."}


AUTO_CLIENT = ServerLC79AutoClient()
autobet_step_busy = False
autobet_bal_counter = 0


def format_vnd(n):
    num = int(round(float(n or 0)))
    sign = "-" if num < 0 else ""
    return f"{sign}{abs(num):,}".replace(",", ".")


def ab_add_log(text, log_type="info"):
    with state_lock:
        ab = SYSTEM_STATE["autobet"]
        ab["logs"].insert(0, {"time": vn_now_str(), "text": text, "type": log_type})
        if len(ab["logs"]) > 80:
            ab["logs"] = ab["logs"][:80]
        save_persisted_state()


def ab_remaining_cap(ab):
    return max(0, int(ab["capital"]) - int(ab["totalLossAmount"]))


def ab_stop_session(reason="Người dùng dừng Auto Cược"):
    with state_lock:
        ab = SYSTEM_STATE["autobet"]
        if not ab["isRunning"]:
            return
        ab["isRunning"] = False
        ab["statusHeadline"] = "Đã dừng Auto Cược"
        ab["statusDetail"] = reason
        ab["statusStage"] = "idle"
        ab["summaryReason"] = reason
    ab_add_log(f"Dừng Auto Cược: {reason} | Lời/lỗ ròng: {format_vnd(SYSTEM_STATE['autobet']['netProfit'])}đ", "warn")


def ab_handle_settlement(session_id, won, round_net, actual_tx, dice, total_pt):
    with state_lock:
        ab = SYSTEM_STATE["autobet"]
        ab["netProfit"] += int(round(round_net))
        did_reset = False
        if won:
            ab["wins"] += 1
            ab["consecutiveLosses"] = 0
            ab["consecutiveWins"] = int(ab.get("consecutiveWins", 0)) + 1
            if ab["consecutiveWins"] > int(ab.get("maxWinStreak", 0)):
                ab["maxWinStreak"] = ab["consecutiveWins"]
            if ab["consecutiveWins"] >= 3:
                if int(ab.get("lossStopCounter", 0)) > 0:
                    did_reset = True
                ab["lossStopCounter"] = 0
        else:
            ab["losses"] += 1
            ab["consecutiveLosses"] += 1
            ab["consecutiveWins"] = 0
            if ab["consecutiveLosses"] > int(ab.get("maxLossStreak", 0)):
                ab["maxLossStreak"] = ab["consecutiveLosses"]
            ab["lossStopCounter"] = int(ab.get("lossStopCounter", 0)) + 1
            ab["totalLossAmount"] += abs(int(round(round_net)))

        ab["balance"] = ab_remaining_cap(ab)
        pick_txt = "Tài" if ab["lastBetSide"] == "T" else "Xỉu"
        act_txt = "Tài" if actual_tx == "T" else "Xỉu"
        dice_str = f"[{'-'.join(map(str, dice))}] = {total_pt} ({act_txt})" if len(dice) == 3 else act_txt

        if won:
            reset_note = " • Reset số lần thua dừng về 0" if did_reset else ""
            ab["statusHeadline"] = f"THẮNG PHIÊN #{session_id} • ĐANG CHỜ PHIÊN KẾ TIẾP"
            ab["statusDetail"] = f"Lời phiên: +{format_vnd(abs(round_net))}đ | Tổng lời: {format_vnd(ab['netProfit'])}đ | Vốn cố định: {format_vnd(ab['balance'])}đ{reset_note}"
            ab["statusStage"] = "waiting"
            log_msg = f"THẮNG Phiên #{session_id} ({dice_str}) • Đặt {pick_txt} {format_vnd(ab['lastBetAmount'])}đ • Lời: +{format_vnd(abs(round_net))}đ • Tổng: {format_vnd(ab['netProfit'])}đ"
            log_t = "win"
        else:
            ab["statusHeadline"] = f"THUA PHIÊN #{session_id} • ĐANG CHỜ PHIÊN KẾ TIẾP"
            ab["statusDetail"] = f"Lỗ phiên: -{format_vnd(abs(round_net))}đ | Tổng lời: {format_vnd(ab['netProfit'])}đ | Vốn còn lại: {format_vnd(ab['balance'])}đ"
            ab["statusStage"] = "waiting"
            log_msg = f"THUA Phiên #{session_id} ({dice_str}) • Đặt {pick_txt} {format_vnd(ab['lastBetAmount'])}đ • Lỗ: -{format_vnd(abs(round_net))}đ • Tổng: {format_vnd(ab['netProfit'])}đ"
            log_t = "loss"

    ab_add_log(log_msg, log_t)

    with state_lock:
        ab = SYSTEM_STATE["autobet"]
        if ab["maxLosses"] > 0 and ab["lossStopCounter"] >= ab["maxLosses"]:
            ab_stop_session(f"Đã chạm giới hạn số lần thua: {ab['lossStopCounter']}/{ab['maxLosses']} lần — Tool tự động dừng")
            return
        if ab["targetProfit"] > 0 and ab["netProfit"] >= ab["targetProfit"]:
            ab_stop_session(f"Đạt mục tiêu lời +{format_vnd(ab['targetProfit'])}đ (Thực đạt: +{format_vnd(ab['netProfit'])}đ)")
            return
        if ab["balance"] < ab["betAmount"]:
            ab_stop_session(f"Đã dùng hết vốn cố định ({format_vnd(ab['capital'])}đ) — Vốn còn lại {format_vnd(ab['balance'])}đ")
            return


def run_autobet_tick_247():
    global autobet_step_busy, autobet_bal_counter
    if SYSTEM_STATE["webStatus"] == "DISABLED":
        if SYSTEM_STATE["autobet"]["isRunning"]:
            ab_stop_session("Hệ thống đã bị vô hiệu hóa bởi Admin")
        return

    with state_lock:
        ab = SYSTEM_STATE["autobet"]
        if not ab["isRunning"] or autobet_step_busy:
            return
        autobet_step_busy = True
        ab["lastHeartbeatTs"] = int(time.time() * 1000)

    try:
        if not AUTO_CLIENT.is_logged_in:
            AUTO_CLIENT.login(ab["username"], ab["password"])

        autobet_bal_counter += 1
        if autobet_bal_counter % 3 == 1:
            fb = AUTO_CLIENT.fetch_balance_strict()
            if fb is not None and fb >= 0:
                with state_lock:
                    ab["realAccountBalance"] = fb

        with state_lock:
            md5_st = SYSTEM_STATE["streams"]["md5"]
            hist = list(md5_st["history"])
            api_pred = md5_st["prediction"]
            api_conf = float(md5_st["confidence"] or 0)
            api_next = md5_st["nextSession"]

        if not hist:
            return

        cur_sess = int(hist[0]["session"])
        with state_lock:
            ab["currentSessionId"] = cur_sess
            if ab["initialSessionId"] is None:
                ab["initialSessionId"] = cur_sess

        # 1. Đối soát phiên đã đặt
        if ab["lastBetSession"] is not None and (ab["lastProcessedSession"] is None or ab["lastProcessedSession"] < ab["lastBetSession"]):
            matched = next((x for x in hist if int(x["session"]) == int(ab["lastBetSession"])), None)
            if matched:
                won = (matched["tx"] == ab["lastBetSide"])
                stake = int(ab["lastBetAmount"])
                if won:
                    actual_bal = AUTO_CLIENT.fetch_balance_strict()
                    credited = round(stake * 1.98)
                    if actual_bal is not None and actual_bal > ab["lastApiPostBalance"]:
                        diff = actual_bal - ab["lastApiPostBalance"]
                        if round(stake * 1.90) <= diff <= round(stake * 2.05):
                            credited = diff
                        with state_lock:
                            ab["realAccountBalance"] = actual_bal
                    round_net = credited - stake
                else:
                    round_net = -stake
                    fb = AUTO_CLIENT.fetch_balance_strict()
                    if fb is not None:
                        with state_lock:
                            ab["realAccountBalance"] = fb

                with state_lock:
                    ab["lastProcessedSession"] = int(matched["session"])
                    ab["lastActivityTs"] = int(time.time() * 1000)
                ab_handle_settlement(int(matched["session"]), won, round_net, matched["tx"], matched.get("dice", []), matched.get("sum", 0))
                if not SYSTEM_STATE["autobet"]["isRunning"]:
                    return
            elif cur_sess > int(ab["lastBetSession"]):
                stake = int(ab["lastBetAmount"])
                actual_bal = AUTO_CLIENT.fetch_balance_strict()
                won = False
                round_net = -stake
                if actual_bal is not None and actual_bal > ab["lastApiPostBalance"]:
                    diff = actual_bal - ab["lastApiPostBalance"]
                    credited = diff if round(stake * 1.90) <= diff <= round(stake * 2.05) else round(stake * 1.98)
                    round_net = credited - stake
                    won = True
                    with state_lock:
                        ab["realAccountBalance"] = actual_bal
                settled_sid = int(ab["lastBetSession"])
                with state_lock:
                    ab["lastProcessedSession"] = settled_sid
                    ab["lastActivityTs"] = int(time.time() * 1000)
                opp = "X" if ab["lastBetSide"] == "T" else "T"
                ab_handle_settlement(settled_sid, won, round_net, ab["lastBetSide"] if won else opp, [], 0)
                if not SYSTEM_STATE["autobet"]["isRunning"]:
                    return

        # Chờ phiên đặt xong
        if ab["lastBetSession"] is not None and (ab["lastProcessedSession"] is None or ab["lastProcessedSession"] < ab["lastBetSession"]):
            if int(ab["lastBetSession"]) > cur_sess:
                with state_lock:
                    ab["statusHeadline"] = f"Đang chờ kết quả phiên #{ab['lastBetSession']}..."
                    ab["statusDetail"] = f"Đã vào lệnh {'TÀI' if ab['lastBetSide'] == 'T' else 'XỈU'} • {format_vnd(ab['lastBetAmount'])}đ | Vốn cố định: {format_vnd(ab['capital'])}đ"
                    ab["statusStage"] = "waiting"
                return

        target_sess = cur_sess + 1
        with state_lock:
            ab["nextSessionId"] = target_sess

        if target_sess in ab["placedSessions"] or ab["lastBetSession"] == target_sess:
            return

        if api_pred not in ("T", "X") or api_next != target_sess:
            return

        # Kiểm tra bộ lọc chế độ vào lệnh
        mode = ab.get("betMode", "safe")
        allowed = True
        reason = f"Theo tất cả ({api_conf}%)"
        if mode == "safe":
            if api_conf > 57:
                reason = f"An toàn đạt chuẩn ({api_conf}% > 57%)"
            else:
                allowed = False
                reason = f"Chế độ An toàn chỉ theo trên 57% (hiện tại {api_conf}%)"
        elif mode == "medium":
            if api_conf >= 54:
                reason = f"Trung bình đạt chuẩn ({api_conf}% ≥ 54%)"
            else:
                allowed = False
                reason = f"Chế độ Trung bình yêu cầu ≥ 54% (hiện tại {api_conf}%)"

        pick_txt = "TÀI" if api_pred == "T" else "XỈU"
        if not allowed:
            with state_lock:
                ab["lastActivityTs"] = int(time.time() * 1000)
                ab["statusHeadline"] = f"CHỜ PHIÊN ĐẸP • BỎ QUA #{target_sess} ({pick_txt} • {api_conf}%)"
                ab["statusDetail"] = f"{reason} — Hệ thống đang quét phiên tiếp theo..."
                ab["statusStage"] = "waiting"
                should_log = (ab["lastSkippedSession"] != target_sess)
                if should_log:
                    ab["lastSkippedSession"] = target_sess
            if should_log:
                ab_add_log(f"Bỏ qua Phiên #{target_sess} ({pick_txt} • {api_conf}%) — {reason}", "info")
            return

        stake = int(ab["betAmount"])
        rem_cap = ab_remaining_cap(ab)
        if rem_cap < stake:
            ab_stop_session(f"Đã dùng hết vốn cố định ({format_vnd(ab['capital'])}đ)")
            return

        bet_res = AUTO_CLIENT.place_bet(api_pred, stake, target_sess, cur_sess, rem_cap)
        if not bet_res.get("ok"):
            r_code = bet_res.get("reason", "")
            if r_code == "insufficient_balance":
                ab_stop_session(f"Số dư tài khoản thực tế không đủ cho mức cược {format_vnd(stake)}đ")
            elif r_code == "capital_limit_exceeded":
                ab_stop_session(f"Đã chạm giới hạn vốn cố định ({format_vnd(ab['capital'])}đ)")
            elif r_code in ("out_of_time_exhausted", "invalid_session"):
                with state_lock:
                    ab["statusHeadline"] = "Đang chờ mở cược phiên kế tiếp..."
                    ab["statusDetail"] = f"Phiên hiện tại đã đóng cược, tự động vào lệnh ở phiên #{target_sess}..."
                    ab["statusStage"] = "waiting"
            else:
                with state_lock:
                    ab["consecutiveBetErrors"] += 1
                    ab["statusHeadline"] = "Tạm gián đoạn đặt lệnh — Đang tự phục hồi..."
                    ab["statusDetail"] = bet_res.get("message", "Thử lại sau 2 giây...")
                    ab["statusStage"] = "loading"
                if ab["consecutiveBetErrors"] >= 2:
                    AUTO_CLIENT.relogin_if_needed()
            return

        placed_sid = int(bet_res["session"])
        with state_lock:
            ab["placedSessions"].append(placed_sid)
            ab["consecutiveBetErrors"] = 0
            ab["lastActivityTs"] = int(time.time() * 1000)
            ab["lastBetSession"] = placed_sid
            ab["lastBetSide"] = api_pred
            ab["lastBetAmount"] = stake
            ab["nextSessionId"] = placed_sid + 1
            ab["preBetBalance"] = rem_cap
            ab["lastApiPostBalance"] = int(bet_res.get("postBalance", AUTO_CLIENT.balance))
            ab["realAccountBalance"] = ab["lastApiPostBalance"]
            if not bet_res.get("settledImmediately"):
                ab["balance"] = max(0, rem_cap - stake)
            ab["statusHeadline"] = f"ĐÃ VÀO LỆNH PHIÊN #{placed_sid}: {pick_txt} ({api_conf}%)"
            ab["statusDetail"] = f"Cược: {format_vnd(stake)}đ | Vốn cố định: {format_vnd(ab['capital'])}đ"
            ab["statusStage"] = "betting"

        ab_add_log(
            f"Vào lệnh Phiên #{placed_sid}: Theo {pick_txt} ({api_conf}%) • Cược {format_vnd(stake)}đ • Vốn cố định: {format_vnd(ab['capital'])}đ • Ví: {format_vnd(ab['realAccountBalance'])}đ",
            "bet"
        )

        if bet_res.get("settledImmediately"):
            won = bool(bet_res.get("won"))
            r_net = (round(stake * 1.98) - stake) if won else -stake
            with state_lock:
                ab["lastProcessedSession"] = placed_sid
            opp = "X" if api_pred == "T" else "T"
            ab_handle_settlement(placed_sid, won, r_net, api_pred if won else opp, [], 0)
    except Exception as e:
        ab_add_log(f"Lỗi tạm thời vòng quét 24/24: {e}", "warn")
    finally:
        autobet_step_busy = False


# ==============================================================================
# VÒNG LẶP NỀN 24/24 TRÊN SERVER (CHẠY LIÊN TỤC KỂ CẢ KHI ĐÓNG TRÌNH DUYỆT)
# ==============================================================================
def background_worker_247():
    last_ping_ts = 0
    while True:
        try:
            update_stream_cycle("md5")
            update_stream_cycle("tx")
            run_autobet_tick_247()

            # Tự ping giữ Render luôn thức 24/24 nếu có cấu hình RENDER_EXTERNAL_URL
            if RENDER_EXTERNAL_URL and (time.time() - last_ping_ts > 240):
                last_ping_ts = time.time()
                try:
                    HTTP.get(f"{RENDER_EXTERNAL_URL.rstrip('/')}/ping", timeout=6)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(2.0)


# ==============================================================================
# TELEGRAM ADMIN BOT QUẢN LÝ HỆ THỐNG (KHÓA / MỞ / BẢO TRÌ / VÔ HIỆU HÓA / THÔNG BÁO)
# ==============================================================================
def tg_api_call(method, payload=None):
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        res = requests.post(url, json=payload or {}, timeout=25)
        return res.json() if res.ok else None
    except Exception:
        return None


def tg_admin_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🔓 Mở Web", "callback_data": "cmd_unlock"},
                {"text": "🔒 Khóa Web", "callback_data": "cmd_lock"}
            ],
            [
                {"text": "🛠 Bảo Trì", "callback_data": "cmd_maintenance"},
                {"text": "⛔ Vô Hiệu Hóa Web", "callback_data": "cmd_disable"}
            ],
            [
                {"text": "📢 Thông Báo Trên Web", "callback_data": "cmd_announce"},
                {"text": "🗑 Xóa Thông Báo", "callback_data": "cmd_clear_announce"}
            ],
            [
                {"text": "📊 Trạng Thái Hệ Thống", "callback_data": "cmd_status"}
            ]
        ]
    }


def tg_build_status_text():
    with state_lock:
        ws = SYSTEM_STATE["webStatus"]
        ann = SYSTEM_STATE["announcement"] or "Không có"
        md5 = SYSTEM_STATE["streams"]["md5"]
        tx = SYSTEM_STATE["streams"]["tx"]
        ab = SYSTEM_STATE["autobet"]

        status_badge = {
            "ACTIVE": "🟢 ĐANG HOẠT ĐỘNG (MỞ)",
            "LOCKED": "🔒 ĐANG KHÓA WEB",
            "MAINTENANCE": "🛠 ĐANG BẢO TRÌ",
            "DISABLED": "⛔ ĐÃ VÔ HIỆU HÓA"
        }.get(ws, ws)

        return (
            f"👑 *LC79 VIP ADMIN CONTROL PANEL*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 *Trạng thái Web:* {status_badge}\n"
            f"📢 *Thông báo Web:* `{ann}`\n"
            f"⏱ *Cập nhật lúc:* `{vn_full_str()}`\n\n"
            f"🤖 *Engine 24/24 MD5:*\n"
            f"• Phiên kế: `#{md5['nextSession'] or '---'}` → *{md5['predictionText']}* (`{md5['confidence']}%`)\n"
            f"• Thắng/Thua: `{md5['wins']}W - {md5['losses']}L` | Chuỗi Max: `{md5['maxWinStreak']}W / {md5['maxLossStreak']}L`\n\n"
            f"🎲 *Engine 24/24 TX HŨ:*\n"
            f"• Phiên kế: `#{tx['nextSession'] or '---'}` → *{tx['predictionText']}* (`{tx['confidence']}%`)\n"
            f"• Thắng/Thua: `{tx['wins']}W - {tx['losses']}L` | Chuỗi Max: `{tx['maxWinStreak']}W / {tx['maxLossStreak']}L`\n\n"
            f"⚡ *Auto Cược MD5 24/24:* `{'ĐANG CHẠY (' + ab['username'] + ')' if ab['isRunning'] else 'ĐANG DỪNG'}`\n"
            f"• Lời/Lỗ ròng: `{format_vnd(ab['netProfit'])}đ`"
        )


def tg_apply_admin_command(chat_id, cmd_action, extra_text=""):
    with state_lock:
        if cmd_action == "unlock":
            SYSTEM_STATE["webStatus"] = "ACTIVE"
            SYSTEM_STATE["statusMessage"] = ""
            reply = "✅ Đã **MỞ WEB**! Người dùng có thể truy cập và sử dụng bình thường."
        elif cmd_action == "lock":
            SYSTEM_STATE["webStatus"] = "LOCKED"
            SYSTEM_STATE["statusMessage"] = extra_text or "Hệ thống tạm thời khóa bởi Quản Trị Viên (@vkhanh3010 • @dvk3010)."
            reply = f"🔒 Đã **KHÓA WEB** thành công!\nLý do: `{SYSTEM_STATE['statusMessage']}`"
        elif cmd_action == "maintenance":
            SYSTEM_STATE["webStatus"] = "MAINTENANCE"
            SYSTEM_STATE["statusMessage"] = extra_text or "Hệ thống đang bảo trì nâng cấp máy chủ AI 24/24. Vui lòng quay lại sau!"
            reply = f"🛠 Đã bật chế độ **BẢO TRÌ WEB**!\nNội dung: `{SYSTEM_STATE['statusMessage']}`"
        elif cmd_action == "disable":
            SYSTEM_STATE["webStatus"] = "DISABLED"
            SYSTEM_STATE["statusMessage"] = extra_text or "Hệ thống đã bị vô hiệu hóa hoàn toàn bởi Quản Trị Viên."
            reply = f"⛔ Đã **VÔ HIỆU HÓA WEB** & dừng mọi tác vụ chạy tự động!"
        elif cmd_action == "announce":
            if not extra_text:
                return None
            SYSTEM_STATE["announcement"] = extra_text
            reply = f"📢 Đã phát **THÔNG BÁO TRÊN WEB**:\n`{extra_text}`"
        elif cmd_action == "clear_announce":
            SYSTEM_STATE["announcement"] = ""
            reply = "🗑 Đã **XÓA THÔNG BÁO** trên Web."
        else:
            reply = tg_build_status_text()
        save_persisted_state()

    tg_api_call("sendMessage", {
        "chat_id": chat_id,
        "text": reply,
        "parse_mode": "Markdown",
        "reply_markup": tg_admin_keyboard()
    })


def telegram_bot_worker():
    if not TELEGRAM_BOT_TOKEN:
        return
    offset = 0
    # Xóa webhook cũ nếu có để polling hoạt động trơn tru
    tg_api_call("deleteWebhook", {"drop_pending_updates": False})

    while True:
        try:
            res = tg_api_call("getUpdates", {"offset": offset, "timeout": 20, "allowed_updates": ["message", "callback_query"]})
            if not res or not res.get("ok"):
                time.sleep(3)
                continue

            for upd in res.get("result", []):
                offset = upd["update_id"] + 1

                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    cq_id = cq.get("id")
                    chat_id = cq.get("message", {}).get("chat", {}).get("id")
                    data = cq.get("data", "")
                    tg_api_call("answerCallbackQuery", {"callback_query_id": cq_id})

                    if not chat_id:
                        continue
                    with state_lock:
                        if not SYSTEM_STATE["adminIds"]:
                            SYSTEM_STATE["adminIds"].append(int(chat_id))
                            save_persisted_state()
                        is_admin = int(chat_id) in SYSTEM_STATE["adminIds"]

                    if not is_admin:
                        tg_api_call("sendMessage", {"chat_id": chat_id, "text": f"⛔ Bạn không có quyền Admin! ID của bạn: `{chat_id}`", "parse_mode": "Markdown"})
                        continue

                    if data == "cmd_announce":
                        with state_lock:
                            SYSTEM_STATE["pendingAdminAction"][str(chat_id)] = "announce"
                        tg_api_call("sendMessage", {
                            "chat_id": chat_id,
                            "text": "📢 Vui lòng gửi **nội dung thông báo** muốn hiển thị lên Web ngay bây giờ (hoặc gửi `/huy` để hủy):",
                            "parse_mode": "Markdown"
                        })
                    elif data.startswith("cmd_"):
                        tg_apply_admin_command(chat_id, data.replace("cmd_", "", 1))

                elif "message" in upd:
                    msg = upd["message"]
                    chat_id = msg.get("chat", {}).get("id")
                    text = str(msg.get("text") or "").strip()
                    if not chat_id or not text:
                        continue

                    with state_lock:
                        if not SYSTEM_STATE["adminIds"]:
                            SYSTEM_STATE["adminIds"].append(int(chat_id))
                            save_persisted_state()
                        is_admin = int(chat_id) in SYSTEM_STATE["adminIds"]

                    if not is_admin:
                        tg_api_call("sendMessage", {
                            "chat_id": chat_id,
                            "text": f"⛔ Truy cập bị từ chối. Chat ID của bạn là `{chat_id}`.",
                            "parse_mode": "Markdown"
                        })
                        continue

                    pending = SYSTEM_STATE["pendingAdminAction"].get(str(chat_id))
                    if pending == "announce":
                        with state_lock:
                            SYSTEM_STATE["pendingAdminAction"].pop(str(chat_id), None)
                        if text.lower() in ("/huy", "huy", "/cancel"):
                            tg_api_call("sendMessage", {"chat_id": chat_id, "text": "❌ Đã hủy thao tác gửi thông báo.", "reply_markup": tg_admin_keyboard()})
                        else:
                            tg_apply_admin_command(chat_id, "announce", text)
                        continue

                    parts = text.split(" ", 1)
                    cmd = parts[0].lower().split("@")[0]
                    arg = parts[1].strip() if len(parts) > 1 else ""

                    if cmd in ("/start", "/menu", "/admin"):
                        tg_api_call("sendMessage", {
                            "chat_id": chat_id,
                            "text": tg_build_status_text(),
                            "parse_mode": "Markdown",
                            "reply_markup": tg_admin_keyboard()
                        })
                    elif cmd in ("/mo", "/unlock"):
                        tg_apply_admin_command(chat_id, "unlock", arg)
                    elif cmd in ("/khoa", "/lock"):
                        tg_apply_admin_command(chat_id, "lock", arg)
                    elif cmd in ("/baotri", "/maintenance"):
                        tg_apply_admin_command(chat_id, "maintenance", arg)
                    elif cmd in ("/vohieuhoa", "/disable"):
                        tg_apply_admin_command(chat_id, "disable", arg)
                    elif cmd in ("/thongbao", "/announce"):
                        if arg:
                            tg_apply_admin_command(chat_id, "announce", arg)
                        else:
                            with state_lock:
                                SYSTEM_STATE["pendingAdminAction"][str(chat_id)] = "announce"
                            tg_api_call("sendMessage", {"chat_id": chat_id, "text": "📢 Nhập nội dung thông báo hiển thị lên Web:", "parse_mode": "Markdown"})
                    elif cmd in ("/xoathongbao", "/clear"):
                        tg_apply_admin_command(chat_id, "clear_announce")
                    elif cmd == "/status":
                        tg_apply_admin_command(chat_id, "status")
                    elif cmd == "/addadmin" and arg.isdigit():
                        new_id = int(arg)
                        with state_lock:
                            if new_id not in SYSTEM_STATE["adminIds"]:
                                SYSTEM_STATE["adminIds"].append(new_id)
                                save_persisted_state()
                        tg_api_call("sendMessage", {"chat_id": chat_id, "text": f"✅ Đã thêm Admin ID `{new_id}`.", "parse_mode": "Markdown"})
                    else:
                        tg_api_call("sendMessage", {
                            "chat_id": chat_id,
                            "text": "📌 *LỆNH ADMIN HỖ TRỢ:*\n• `/admin` — Mở bảng điều khiển nút bấm\n• `/khoa [lý do]` — Khóa Web\n• `/mo` — Mở Web\n• `/baotri [nội dung]` — Bật chế độ bảo trì\n• `/vohieuhoa [lý do]` — Vô hiệu hóa Web\n• `/thongbao <nội dung>` — Gửi thông báo lên Web\n• `/xoathongbao` — Xóa thông báo Web\n• `/status` — Xem trạng thái 24/24",
                            "parse_mode": "Markdown",
                            "reply_markup": tg_admin_keyboard()
                        })
        except Exception:
            time.sleep(3)


# Khởi chạy 2 luồng nền 24/24 ngay khi server khởi động
threading.Thread(target=background_worker_247, daemon=True).start()
threading.Thread(target=telegram_bot_worker, daemon=True).start()


# ==============================================================================
# ROUTES WEB & CÁC ENDPOINT MÃ HÓA ẨN (KHÔNG LỘ URL UPSTREAM TRONG NETWORK LOG)
# ==============================================================================
@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@app.route("/", methods=["GET"])
def serve_index():
    resp = send_from_directory(".", "index.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/_s/app.js", methods=["GET"])
def serve_client_bundle():
    resp = send_from_directory(".", "app_client.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_check():
    return jsonify({"ok": True, "ts": int(time.time() * 1000)})


# /_s/st : Trạng thái hệ thống Admin (Khóa / Mở / Bảo trì / Vô hiệu hóa / Thông báo)
@app.route("/_s/st", methods=["POST"])
def route_sys_status():
    ok, _ = verify_client_sig()
    if not ok:
        return Response(status=403)
    with state_lock:
        payload = {
            "ws": SYSTEM_STATE["webStatus"],
            "sm": SYSTEM_STATE["statusMessage"],
            "an": SYSTEM_STATE["announcement"],
            "bg": True
        }
    return secure_json_response(payload)


# /_s/k1 : Xác minh Key lần đầu
@app.route("/_s/k1", methods=["POST"])
def route_key_verify():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    key_val = str(data.get("k") or "").strip()
    dev_val = str(data.get("d") or "").strip()
    result = verify_vip_key_full(key_val, dev_val, check_device_too=True)
    return secure_json_response(result)


# /_s/k2 : Kiểm tra Key liên tục 24/24 (khóa ngay nếu key bị khóa hoặc hết hạn)
@app.route("/_s/k2", methods=["POST"])
def route_key_continuous():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    key_val = str(data.get("k") or "").strip()
    dev_val = str(data.get("d") or "").strip()
    result = verify_vip_key_full(key_val, dev_val, check_device_too=True)
    return secure_json_response(result)


# /_s/p1 : Dữ liệu 24/24 cho Robot Mode (TX & MD5)
@app.route("/_s/p1", methods=["POST"])
def route_robot_sync():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    with state_lock:
        if SYSTEM_STATE["webStatus"] != "ACTIVE":
            return secure_json_response({"blocked": True, "ws": SYSTEM_STATE["webStatus"]})
        md5 = SYSTEM_STATE["streams"]["md5"]
        tx = SYSTEM_STATE["streams"]["tx"]
        out = {
            "md5": {
                "currentSession": md5["currentSession"],
                "nextSession": md5["nextSession"],
                "prediction": md5["predictionText"],
                "confidence": md5["confidence"],
                "apiOnline": md5["apiOnline"],
                "wins": md5["wins"],
                "losses": md5["losses"],
                "maxWinStreak": md5["maxWinStreak"],
                "maxLossStreak": md5["maxLossStreak"]
            },
            "tx": {
                "currentSession": tx["currentSession"],
                "nextSession": tx["nextSession"],
                "prediction": tx["predictionText"],
                "confidence": tx["confidence"],
                "apiOnline": tx["apiOnline"],
                "wins": tx["wins"],
                "losses": tx["losses"],
                "maxWinStreak": tx["maxWinStreak"],
                "maxLossStreak": tx["maxLossStreak"]
            }
        }
    return secure_json_response(out)


# /_s/p2 : Dữ liệu 24/24 cho Direct Mode (MD5 + Lịch sử + Chuỗi thắng thua cao nhất)
@app.route("/_s/p2", methods=["POST"])
def route_direct_sync():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    with state_lock:
        if SYSTEM_STATE["webStatus"] != "ACTIVE":
            return secure_json_response({"blocked": True, "ws": SYSTEM_STATE["webStatus"]})
        md5 = SYSTEM_STATE["streams"]["md5"]
        out = {
            "currentSession": md5["currentSession"],
            "nextSession": md5["nextSession"],
            "prediction": md5["predictionText"],
            "confidence": md5["confidence"],
            "apiOnline": md5["apiOnline"],
            "wins": md5["wins"],
            "losses": md5["losses"],
            "currentWinStreak": md5["currentWinStreak"],
            "currentLossStreak": md5["currentLossStreak"],
            "maxWinStreak": md5["maxWinStreak"],
            "maxLossStreak": md5["maxLossStreak"],
            "history": md5["history"][:45],
            "preds": dict(list(md5["preds"].items())[-60:])
        }
    return secure_json_response(out)


# /_s/a1 : Kiểm tra số dư tài khoản LC79 cho AutoBet
@app.route("/_s/a1", methods=["POST"])
def route_ab_check_balance():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    if SYSTEM_STATE["webStatus"] != "ACTIVE":
        return secure_json_response({"ok": False, "message": "Hệ thống đang tạm khóa/bảo trì."})
    user = str(data.get("u") or "").strip()
    pwd = str(data.get("p") or "").strip()
    if not user or not pwd:
        return secure_json_response({"ok": False, "message": "❌ Vui lòng nhập đầy đủ Tài khoản và Mật khẩu LC79."})
    res = AUTO_CLIENT.login(user, pwd)
    if res.get("ok"):
        with state_lock:
            SYSTEM_STATE["autobet"]["realAccountBalance"] = res["balance"]
            save_persisted_state()
    return secure_json_response(res)


# /_s/a2 : Khởi chạy Auto Phân Tích • Cược 24/24 trên Server
@app.route("/_s/a2", methods=["POST"])
def route_ab_start():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    if SYSTEM_STATE["webStatus"] != "ACTIVE":
        return secure_json_response({"ok": False, "message": "Hệ thống đang tạm khóa/bảo trì."})

    user = str(data.get("u") or "").strip()
    pwd = str(data.get("p") or "").strip()
    raw_cap = int(data.get("cap") or 0)
    target_profit = int(data.get("tp") or 0)
    max_losses = int(data.get("ml") if data.get("ml") is not None else 3)
    bet_amount = int(data.get("bet") or 1000)
    bet_mode = str(data.get("mode") or "safe")
    if bet_mode not in ("safe", "medium", "all"):
        bet_mode = "safe"

    if not user or not pwd:
        return secure_json_response({"ok": False, "tab": "login", "message": "Vui lòng nhập đầy đủ Tài khoản và Mật khẩu LC79 ở Tab 1."})
    if bet_amount < 1000:
        return secure_json_response({"ok": False, "tab": "settings", "message": "Số tiền cược mỗi tay tối thiểu phải từ 1.000đ trở lên."})
    if raw_cap > 0 and bet_amount > raw_cap:
        return secure_json_response({"ok": False, "tab": "settings", "message": f"Tiền cược ({format_vnd(bet_amount)}đ) lớn hơn vốn cố định ({format_vnd(raw_cap)}đ)."})

    login_res = AUTO_CLIENT.login(user, pwd)
    if not login_res.get("ok"):
        return secure_json_response({"ok": False, "tab": "login", "message": login_res.get("message", "Đăng nhập thất bại.")})

    acc_bal = int(login_res.get("balance", 0))
    if acc_bal < 1000:
        return secure_json_response({"ok": False, "tab": "login", "message": f"Số dư thực tế ({format_vnd(acc_bal)}đ) không đủ mức cược tối thiểu 1.000đ."})

    eff_cap = acc_bal if raw_cap == 0 else raw_cap
    if acc_bal < eff_cap:
        return secure_json_response({"ok": False, "tab": "settings", "message": f"Số dư thực tế ({format_vnd(acc_bal)}đ) không đủ cho vốn cố định ({format_vnd(eff_cap)}đ)."})
    if acc_bal < bet_amount or eff_cap < bet_amount:
        return secure_json_response({"ok": False, "tab": "settings", "message": f"Số dư / vốn cố định không đủ cho mức cược {format_vnd(bet_amount)}đ/tay."})

    with state_lock:
        old_logs = SYSTEM_STATE["autobet"]["logs"]
        new_ab = make_autobet_state()
        new_ab.update({
            "isRunning": True,
            "username": user,
            "password": pwd,
            "rawCapitalInput": raw_cap,
            "capital": eff_cap,
            "initialBalance": eff_cap,
            "balance": eff_cap,
            "realAccountBalance": acc_bal,
            "targetProfit": target_profit,
            "maxLosses": max_losses,
            "betAmount": bet_amount,
            "betMode": bet_mode,
            "preBetBalance": eff_cap,
            "lastApiPostBalance": acc_bal,
            "statusHeadline": f"ĐANG CHẠY NỀN 24/24 • {bet_mode.upper()}",
            "statusDetail": f"Vốn cố định: {format_vnd(eff_cap)}đ | Cược: {format_vnd(bet_amount)}đ/tay | Chạy liên tục kể cả khi thoát web",
            "statusStage": "waiting",
            "logs": old_logs
        })
        SYSTEM_STATE["autobet"] = new_ab

    ab_add_log(
        f"Bắt đầu Auto Cược 24/24 ({user}) — Vốn cố định: {format_vnd(eff_cap)}đ | Cược: {format_vnd(bet_amount)}đ/tay | Chế độ: {bet_mode}",
        "info"
    )
    return secure_json_response({"ok": True, "state": SYSTEM_STATE["autobet"]})


# /_s/a3 : Dừng Auto Phân Tích • Cược
@app.route("/_s/a3", methods=["POST"])
def route_ab_stop():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    reason = str(data.get("reason") or "Người dùng chủ động dừng Auto Cược")
    ab_stop_session(reason)
    with state_lock:
        st_copy = dict(SYSTEM_STATE["autobet"])
        st_copy.pop("password", None)
    return secure_json_response({"ok": True, "state": st_copy})


# /_s/a4 : Đồng bộ trạng thái AutoBet 24/24 về giao diện
@app.route("/_s/a4", methods=["POST"])
def route_ab_sync():
    data, _ = read_secure_request()
    if data is None:
        return Response(status=403)
    with state_lock:
        if data.get("clearLogs"):
            SYSTEM_STATE["autobet"]["logs"] = []
            save_persisted_state()
        st_copy = dict(SYSTEM_STATE["autobet"])
        st_copy.pop("password", None)
    return secure_json_response({"ok": True, "state": st_copy})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
