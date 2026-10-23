#!/usr/bin/env bash
# Consistency checker for the BARO ERP design package (documents only).
# Run from anywhere:  bash docs/appendix/consistency-checks.sh
# Exit code = number of FAIL checks, so it can gate a docs commit.
cd "$(dirname "$0")/../.." || exit 1
D=docs
X="--exclude=consistency-checks.sh"   # never scan this script's own literals
FAILS=0
fail() { printf 'FAIL %s\n' "$1"; FAILS=$((FAILS+1)); }
pass() { printf 'PASS %s\n' "$1"; }
warn() { printf 'WARN %s\n' "$1"; }

# C1 — every baro_* identifier used anywhere is defined in the data dictionary
grep -ohE 'baro_[a-z_]+' $D/10-data-dictionary.md | sort -u > /tmp/baro_defined.txt
# doc 80 is the defect log: it quotes superseded names verbatim, so it is not evidence of use
grep -rohE 'baro_[a-z_]+' $X --exclude=80-verification-checklist.md $D README.md | sort -u > /tmp/baro_used.txt
# legitimate non-fields: app + internal module names, python file/patch names,
# wildcard prose (baro_active_*_key, baro_last_*), CSV template names
ALLOW='^(baro_core|baro_fleet|baro_devices|baro_connectivity|baro_field_service|baro_billing|baro_integrations|baro_settings|baro_active_|baro_last_|baro_doctypes|baro_device_assignment|baro_customers|baro_items|baro_sims|baro_assignments|baro_vehicles|baro_platform_mappings|baro_subscriptions)'
UNDEF=$(comm -13 /tmp/baro_defined.txt /tmp/baro_used.txt | grep -vE "$ALLOW" | tr '\n' ' ')
[ -z "$UNDEF" ] && pass "C1 field names all defined in $D/10" || fail "C1 undefined baro_* -> $UNDEF"

# C2 — every cross-document section reference resolves to a real heading
grep -rohE '`[0-9]{2}` §[0-9]+(\.[0-9]+)?' $X $D README.md | tr -d '`' | sed 's/§//' \
  | awk '{print $1" "$2}' | sort -u > /tmp/refs.txt
BAD=""
while read -r d s; do
  [ -z "$d" ] && continue
  f=$(ls $D/${d}-*.md 2>/dev/null | head -1)
  [ -z "$f" ] && { BAD="$BAD $d:$s(no-file)"; continue; }
  grep -qE "^#{2,3} ${s}([ .]|$)" "$f" || grep -qE "^#{2,3} ${s}\." "$f" || BAD="$BAD $d:$s"
done < /tmp/refs.txt
[ -z "$BAD" ] && pass "C2 $(wc -l < /tmp/refs.txt) cross-refs resolve" || fail "C2 dangling refs ->$BAD"

# C3 — naming series are uniform and each is declared in doc 10
SERIES=$(grep -rhoE 'BARO-[A-Z]+-\.####' $X $D README.md | grep -v 'BARO-XXX' | sort -u)
MISS=""
for s in $SERIES; do grep -q "$s" $D/10-data-dictionary.md || MISS="$MISS $s"; done
[ -n "$SERIES" ] && [ -z "$MISS" ] \
  && pass "C3 series uniform and declared: $(echo $SERIES | tr '\n' ' ')" \
  || fail "C3 series problem -> missing from $D/10:${MISS:-none}; found:${SERIES:-none}"

# C4 — job names in the conventions doc equal those in the trigger catalogue
j() { grep -rhoE 'flag_[a-z_]+|sync_platform_fleet|process_integration_retries|run_platform_reconciliation|archive_integration_logs' "$1"; }
diff <(j $D/30-schema-conventions.md | sort -u) <(j $D/60-automation-trigger-catalog.md | sort -u) > /tmp/jobs.diff
[ -s /tmp/jobs.diff ] && fail "C4 job-name drift -> $(tr '\n' ' ' < /tmp/jobs.diff)" || pass "C4 job names equal in 30 and 60"

# C5 — the 14 roles doc 41 defines are the only roles cited anywhere
ROLES='BARO Sales Officer|BARO Fleet Officer|BARO Installer|BARO Service Supervisor|BARO Approver|BARO Stock Manager|BARO Connectivity Admin|BARO Support Agent|BARO Accounts User|BARO Finance Approver|BARO Procurement Officer|BARO Report Viewer|BARO Integrator|BARO System Manager'
grep -rohE "($ROLES)" $X $D README.md | sort -u > /tmp/roles_used.txt
UNDEF_ROLE=$(while IFS= read -r r; do
  grep -qF "\`$r\`" $D/41-role-permission-matrix.md || printf ' %s' "$r"
done < /tmp/roles_used.txt)
[ -z "$UNDEF_ROLE" ] && pass "C5 $(wc -l < /tmp/roles_used.txt) role citations resolve to the $D/41 inventory" \
  || fail "C5 role not defined in 41 ->$UNDEF_ROLE"
EXTRA=$(grep -rohE 'BARO [A-Z][a-z]+ [A-Z][a-z]+' $X $D README.md \
  | grep -vE "^($ROLES)$" | sort -u | tr '\n' ';')
[ -z "$EXTRA" ] || warn "C5 non-role 'BARO x y' phrases to eyeball: $EXTRA"

# C6 — enum closure: every status literal compared in the package is a declared enum value
sed -n '/## 6. Enumerations/,$p' $D/10-data-dictionary.md | grep '^|' | tail -n +3 \
  | cut -d'|' -f3 | tr ',' '\n' | sed 's/^ *//;s/ *$//;s/`//g' | grep -v '^$' | sort -u > /tmp/enums.txt
grep -rohE 'baro_[a-z_]*status`? = [A-Za-z][A-Za-z -]{2,20}' $X $D \
  | sed -E 's/.*status`? = //' | sed 's/ *$//' | sort -u > /tmp/status_used.txt
ORPHST=$(comm -23 /tmp/status_used.txt /tmp/enums.txt | grep -vE ' AND |^None$' | tr '\n' ';')
[ -z "$ORPHST" ] && pass "C6 all compared status values are declared enums" || fail "C6 status not in $D/10 §6 -> $ORPHST"

# C7 — code fences balanced per file
BAD7=""
for f in $D/*.md $D/appendix/*.md README.md; do
  n=$(grep -c '^```' "$f"); [ $((n % 2)) -eq 0 ] || BAD7="$BAD7 $f($n)"
done
[ -z "$BAD7" ] && pass "C7 fences balanced across $(ls $D/*.md $D/appendix/*.md README.md | wc -l) files" || fail "C7 unbalanced ->$BAD7"

# C8 — blueprint misnames may appear only as corrections
for bad in project_task 'Baro Platform Settings'; do
  where=$(grep -rl "$bad" $X $D README.md | tr '\n' ' ')
  [ -z "$where" ] && pass "C8 no '$bad'" || warn "C8 '$bad' in: $where (must read as a correction)"
done
grep -rqE 'new (BARO|Baro) (Device|Installation|Service Inspection) (DocType|doctype)' $X $D README.md \
  && fail "C8 a rejected parallel DocType is proposed as new" || pass "C8 no rejected-doctype regression"

# C9 — DocType inventory matches the claim in doc 03 §2
N=$(grep -cE '^### 4\.[0-9]+ `Baro ' $D/10-data-dictionary.md)
[ "$N" -eq 10 ] && pass "C9 doc 10 §4 defines 10 (9 business + 1 Single)" \
  || fail "C9 doc 10 §4 defines $N; doc 03 §2 claims 10"

# C10 — every Tn cited outside doc 60 exists as a row in doc 60 §1
#  (doc 60 §4 pads notification titles to T03; the catalog row id itself is not padded)
TS=$(grep -rohE '\bT[0-9]{1,3}\b' $X $D/10*.md $D/20*.md $D/21*.md $D/30*.md $D/40*.md $D/50*.md $D/51*.md README.md | sort -u)
BAD10=""
for t in $TS; do
  n=$((${t#T}))
  grep -qE "^\| \*\*T$n\*\*" $D/60-automation-trigger-catalog.md || BAD10="$BAD10 $t"
done
[ -z "$BAD10" ] && pass "C10 all cited trigger ids exist in $D/60 §1" || fail "C10 unknown trigger ids ->$BAD10"

echo
echo "checks=10 fails=$FAILS"
exit "$FAILS"
