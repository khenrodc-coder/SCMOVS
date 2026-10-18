#!/bin/sh
# Runs every test suite, each on a freshly rebuilt test database.
export DATABASE_NAME=scmovs_test SECRET_KEY=testkey
cd "$(dirname "$0")/.."
rc=0
for t in test_users test_students_depts test_profile_recovery test_candidates test_phase3_4 test_modals_more test_regression; do
  [ -f tests/$t.py ] || continue
  sh tests/reset_test_db.sh
  echo "=== $t"; (cd tests && python3 $t.py | grep -v '^PASS') || rc=1
done
exit $rc
