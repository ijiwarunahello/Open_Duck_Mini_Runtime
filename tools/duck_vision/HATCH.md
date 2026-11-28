# Codex pet `ducktronics` の hatch 依頼

Mac の Codex (app の `/hatch`、または hatch-pet スキル) にこのファイルを渡す。
進め方と成果物の形は `ijiwarunahello/sung-sun` (hatch-pet の実行結果) と同じにする。

## 参照画像

- 主: `~/Workspaces/src/github.com/ijiwarunahello/ducktronics-hub/local/signs/assets/duck-robot.png`
  (ロボット単体・長いアンテナ・透過。離席中ボードで使った最終版。写真アプリ「ducktronics」アルバムの `ducktronics-robot.png` と同じ)
- 副: `~/Workspaces/src/github.com/ijiwarunahello/ducktronics-hub/local/sticker/assets/robot-walk-sticker-v5-x4.png` (短いアンテナ版)

出自はハブの `docs/research/20261127-robot-logo-assets.md`。どちらも自作機 (Open Duck Mini V2) を元に生成したイラスト。
既存のキャラクターや他社の機体 (Disney の BD-X など) を描くようには指示しない。

## 依頼文

```
Hatch a Codex pet.
pet_id: ducktronics
display_name: ducktronics
description: A small bipedal duck robot that is practising how to walk, curious about everything it sees.
Reference image: <主の参照画像のパス> (canonical design). Keep its head shape, face/eye design,
antennas, body colours and leg design. Simplify into the Codex digital pet sprite style
(chunky silhouette, thick dark outline, limited palette). No text, no extra characters.
Standard 9-row atlas (idle, running-right, running-left, waving, jumping, failed, waiting,
running, review). running = waddling walk in place; failed = wobble and sit down;
review = tilting the head and looking around with the eyes.
Install to ~/.codex/pets/ducktronics/ (pet.json + spritesheet.webp).
```

## 受け入れ条件

- `~/.codex/pets/ducktronics/pet.json` と `spritesheet.webp` (1536×1872、8 列 × 9 行) があり、hatch-pet の validation が `ok`。
- `python3 -m tools.duck_vision.booth_server --pet ~/.codex/pets/ducktronics` で左に表示され、歩く・写真・独り言で行が切り替わる。
