from permissions import is_single_statement as f, normalize_sql as n

assert f("SELECT 1 /* ' */ ; DELETE FROM tasks; /* ' */") is False
assert f('SELECT 1 AS "--"; DELETE FROM tasks') is False
assert f(r"SELECT E'\'' ; DELETE FROM tasks; --'") is False
assert f('SELECT 1; SELECT 2') is False
assert f("SELECT * FROM users WHERE name = 'Vitamin E'") is True
assert f("UPDATE tasks SET status = 'done' WHERE id = 3;") is True
assert 'performance_reviews' in n('SELECT * FROM "performance_reviews"')

print('all good')