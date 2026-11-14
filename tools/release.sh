#!/usr/bin/env bash
# =====================================================================
#  RotorWeb — publier une nouvelle version sur GitHub (à lancer sur le VPS de l'éditeur)
#
#      cd rotorweb-vX.Y
#      ./tools/release.sh              # prépare, signe et publie
#      ./tools/release.sh --dry-run    # prépare et signe seulement (rien n'est publié)
#
#  Prérequis (une seule fois) : gh installé et connecté (gh auth login), openssl, zip, git,
#  et la clé privée ~/.rotorweb-release/rotorweb-signing.key (phrase de passe demandée).
#
#  Publie dans la « Release » vX.Y du dépôt :
#     rotorweb-vX.Y.zip   release.json   release.json.sig
#  et pousse le code source de la version sur la branche main.
# =====================================================================
set -euo pipefail
REPO="${ROTORWEB_REPO:-RadioamateursduFjord/rotorweb}"
KEY="${ROTORWEB_SIGNING_KEY:-$HOME/.rotorweb-release/rotorweb-signing.key}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1
G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1;36m'; N='\033[0m'
ok(){ echo -e "${G}✔ $*${N}"; }; step(){ echo -e "\n${B}==> $*${N}"; }; die(){ echo -e "${R}✖ $*${N}"; exit 1; }

for c in openssl zip python3 sha256sum; do command -v $c >/dev/null || die "commande manquante : $c (sudo apt install $c)"; done
[[ $DRY -eq 1 ]] || { command -v gh >/dev/null || die "gh absent (voir le guide)"; command -v git >/dev/null || die "git absent"; }
[[ -f "$KEY" ]] || die "clé privée introuvable : $KEY"

V=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC/rotorweb/server.py")
[[ -n "$V" ]] || die "numéro de version introuvable dans rotorweb/server.py"
TAG="v$V"; NAME="rotorweb-v$V"
step "RotorWeb $TAG → $REPO"
grep -q "^## v$V " "$SRC/CHANGELOG.md" || die "CHANGELOG.md n'a pas de section « ## v$V »"

if [[ $DRY -eq 0 ]]; then
  gh auth status >/dev/null 2>&1 || die "gh n'est pas connecté : gh auth login"
  if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then die "la version $TAG existe déjà sur GitHub (change le numéro de version)"; fi
fi

OUT="$SRC/../release-$TAG"
rm -rf "$OUT"; mkdir -p "$OUT"
step "Paquet $NAME.zip"
cp -r "$SRC" "$OUT/$NAME"
find "$OUT/$NAME" \( -name __pycache__ -o -name .git -o -name venv -o -name "*.pyc" \) -prune -exec rm -rf {} + 2>/dev/null || true
rm -f "$OUT/$NAME"/config.json* "$OUT/$NAME"/state.json* "$OUT/$NAME"/*.rwbackup
(cd "$OUT" && zip -qr "$NAME.zip" "$NAME")
SHA=$(sha256sum "$OUT/$NAME.zip" | cut -d' ' -f1)
ok "$(du -h "$OUT/$NAME.zip" | cut -f1)  sha256 $SHA"

step "release.json (version, nouveautés, empreinte du zip)"
V="$V" SHA="$SHA" NAME="$NAME" OUT="$OUT" SRC="$SRC" python3 - <<'PY'
import json, os, re, time
v, src = os.environ["V"], os.environ["SRC"]
cl = open(os.path.join(src, "CHANGELOG.md"), encoding="utf-8").read()
def section(english):
    for m in re.finditer(r"^## v" + re.escape(v) + r" .*$", cl, re.M):
        if ("English" in m.group(0)) == english:
            rest = cl[m.end():]
            nxt = re.search(r"^## |^---", rest, re.M)
            return rest[:nxt.start() if nxt else len(rest)].strip()
    return ""
info = {"name": "rotorweb", "version": v, "date": time.strftime("%Y-%m-%d"),
        "zip": os.environ["NAME"] + ".zip", "sha256": os.environ["SHA"],
        "size": os.path.getsize(os.path.join(os.environ["OUT"], os.environ["NAME"] + ".zip")),
        "notes": {"fr": section(False), "en": section(True) or section(False)}}
open(os.path.join(os.environ["OUT"], "release.json"), "w", encoding="utf-8").write(json.dumps(info, ensure_ascii=False, indent=1))
open(os.path.join(os.environ["OUT"], "notes.md"), "w", encoding="utf-8").write(
    info["notes"]["fr"] + "\n\n---\n\n" + info["notes"]["en"] + "\n")
PY
ok "release.json"

step "Signature (phrase de passe de la clé)"
openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$OUT/release.json" -out "$OUT/release.json.sig"
openssl pkeyutl -verify -pubin -inkey "${ROTORWEB_RELEASE_PUB:-$SRC/rotorweb/release.pub}" -rawin -in "$OUT/release.json" -sigfile "$OUT/release.json.sig" >/dev/null 2>&1 \
  || die "la signature ne correspond pas à rotorweb/release.pub : mauvaise clé privée ?"
ok "signature vérifiée avec la clé publique du paquet"

if [[ $DRY -eq 1 ]]; then
  echo -e "\n${Y}Essai seulement (--dry-run) : rien n'est publié.${N} Fichiers prêts dans $OUT"
  exit 0
fi

step "Code source → branche main"
WORK=$(mktemp -d)
gh repo clone "$REPO" "$WORK/repo" -- -q 2>/dev/null || die "impossible de cloner $REPO"
cd "$WORK/repo"
git checkout -q -B main
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -r "$OUT/$NAME/." .
git add -A
if git diff --cached --quiet; then ok "code déjà à jour"; else
  git -c user.name="${GIT_NAME:-RotorWeb release}" -c user.email="${GIT_EMAIL:-rotorweb@users.noreply.github.com}" \
      commit -q -m "RotorWeb $TAG"
  git push -q origin main
  ok "poussé sur main"
fi
cd - >/dev/null; rm -rf "$WORK"

step "Release GitHub $TAG"
gh release create "$TAG" "$OUT/$NAME.zip" "$OUT/release.json" "$OUT/release.json.sig" \
  --repo "$REPO" --target main --title "RotorWeb $TAG" --notes-file "$OUT/notes.md"
ok "Publié : https://github.com/$REPO/releases/tag/$TAG"
echo "   Les stations RotorWeb verront la nouvelle version dans les 24 h (ou tout de suite avec « Vérifier les mises à jour »)."
