# duck-vision: duck から みた せかい

展示用。duck の頭のカメラ映像を 64×48 のドット絵にして、ブースの Mac に「duck の顔 (Codex pet)」と並べて出す。

- カメラには最初から 64×48 で撮らせる。高解像度の画像はどこにも存在せず、ディスクにも保存しない (カメラは来場者を下から見上げるため)。
- 歩行スクリプト (`v2_rl_walk_mujoco.py`) には触らない。止めれば元どおり。
- Pi 側・Mac 側とも Python 標準ライブラリだけで動く (venv 不要)。

```
Pi: rpicam-vid (64x48 MJPEG) → pi_stream.py :8091 ──Wi-Fi──▶ Mac: booth_server.py :8090 → ブラウザ全画面
```

## Pi

```sh
cd ~/duck-vision        # v2_iji の worktree (下の「入れ方」)
python3 -m tools.duck_vision.pi_stream
```

- `rpicam-vid` は `nice -n 10` で動かし、歩行ループを優先する。
- カメラを使っている間は bench GUI の「撮る」(`rpicam-still`) は使えない。
- 確認: Mac から `curl -o x.jpg http://ducktronics.local:8091/frame.jpg`

## Mac

```sh
python3 -m tools.duck_vision.booth_server --pet ~/.codex/pets/ducktronics
open http://localhost:8090
```

- `--pi` の既定は `http://ducktronics.local:8091`。mDNS が引けなければ `--pi http://192.168.0.112:8091`。
- `--pet` を付けないと仮のキャラで動く。
- ページを 1 回クリックすると音が出る (ブラウザの制約)。

| キー | 動作 |
| --- | --- |
| Space | 写真。今のドット絵を 7 秒止めて出す。保存しない |
| R | 映像を 90° 回す (既定 90°。URL の `?rot=0` でも指定できる) |
| P | 色: duck / uv (紫外線ごっこ) |
| M | 音のオン・オフ |
| F | 全画面 |

歩いている / 止まっているは映像の揺れ (フレーム間差分) で推定する。誤判定するときは `?enter=12&exit=6` (0-255) を調整する。

## 実機の状態との連動 (任意)

歩行スクリプトを `DUCK_TELEMETRY=127.0.0.1:8092` (または `--telemetry 127.0.0.1:8092`) 付きで動かすと、10Hz で一時停止・指令・加速度・角速度を UDP で送る。`pi_stream` が受けて `/state.json` で出し、ページはこれを優先して pet を動かす (届かないときは映像の揺れで推定する)。既定はオフ。送信は非ブロッキングで、失敗しても歩行は止まらない。

| 実機 | 判定 | pet |
| --- | --- | --- |
| 歩く | 一時停止でなく、指令が vx/vy 0.02 か wz 0.15 を超える | jumping → running |
| その場旋回 | wz の符号 | running-left / running-right |
| 転倒 | 加速度の向きが 55° 以上 (`?fall=`) 傾いて 0.3 秒 | failed (わっ!) |
| 起こされた | 20° 以内に 1 秒 | jumping (よいしょ) |
| 一時停止 (A) | paused | waiting |
| 持ち上げ | 一時停止中に加速度の大きさが 9.8 から 4 以上ずれる | jumping |

実機への入れ方はハブの `docs/plans/20261128-duck-vision-deploy.md`。

## pet の状態 (映像だけのとき)

Codex pet のアトラス (8 列 × 9 行、192×208) の行をそのまま使う。各行のコマ数は透明でないセルを数えて決める。

| 出来事 | pet | セリフ |
| --- | --- | --- |
| 待機 | idle | 15-30 秒おきに独り言 (`review` 行) |
| 歩き始め | jumping → running | あるくよ 等 |
| 止まった | idle | ふう、とまった 等 |
| 写真 | waving | はい、ちーず 等 |
| 映像が 3 秒途切れた | failed → waiting | あれ? め が みえない… |

声は人の声を使わず、1 文字ごとの電子音 (Web Audio) にしている。

## 入れ方 (展示中、既存の clone を汚さない)

```sh
# Pi と Mac それぞれで
cd ~/Open_Duck_Mini_Runtime     # Mac は自分の clone の場所
git fetch origin v2_iji
git worktree add ~/duck-vision origin/v2_iji
```

## pet を作る (Mac の Codex)

`HATCH.md` を Codex に渡す。
