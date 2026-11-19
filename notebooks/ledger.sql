-- Ledger explorer for the DuckDB command line: the views of statarb.paper.views, in SQL.
--
--     STATARB_LEDGER_ROOT=../stat-arb-forward duckdb -init notebooks/ledger.sql
--
-- STATARB_LEDGER_ROOT is the checkout whose ledger to read, by default the directory DuckDB is started in; the
-- ledger is taken to be in data/paper/ under it, the default of `[paths] paper`. It opens an in-memory database,
-- so nothing is written.
--
-- `FROM guide;` lists the views. Weights are per unit of capital and a `_usd` column is a weight times
-- `book_size`, as in the ledger. tests/test_ledger_sql.py holds each view to the Python view of the same name.
-- Local only: decision record 0003 forbids redistributing the data the ledger derives from.

-- `getenv` exists only in the command-line client; anything else sets the variable `paper` before loading this file.
SET VARIABLE paper = coalesce(getvariable('paper'), coalesce(getenv('STATARB_LEDGER_ROOT'), '.') || '/data/paper');

-- Every ledger day, as stored (docs/data-model.md).
CREATE OR REPLACE VIEW ledger AS
SELECT * FROM read_parquet(getvariable('paper') || '/ledger/date=*.parquet', hive_partitioning = false);

-- The sectors of the latest daily snapshot. The daily job keeps only the snapshot in use; SQL cannot see its
-- COMPLETE marker, so do not query while the job is building one.
CREATE OR REPLACE VIEW sectors AS
WITH files AS (
    SELECT * FROM read_parquet(getvariable('paper') || '/processed/*/sectors.parquet', filename = true)
)
SELECT ticker, sector, valid_from, valid_to FROM files WHERE filename = (SELECT max(filename) FROM files);

-- The ledger with each name's sector on the day; the hedge ETFs have none.
CREATE OR REPLACE VIEW named AS
SELECT l.*, coalesce(s.sector, 'no sector') AS sector
FROM ledger l
LEFT JOIN sectors s
    ON s.ticker = l.ticker AND s.valid_from <= l.date AND (s.valid_to IS NULL OR l.date < s.valid_to);

-- The book after each open's fill: every name held, latest day first and largest first within a day.
-- `prior_expected_move` is the expected move the fill was decided on, which the previous ledger day recorded at
-- its close; the day's own `expected_move` is the decision for the next open, in `next_open`.
CREATE OR REPLACE VIEW book AS
WITH days AS (
    SELECT date, lag(date) OVER (ORDER BY date) AS prior_date FROM (SELECT DISTINCT date FROM ledger)
)
SELECT n.date, n.ticker, n.sector, CASE WHEN n.holding > 0 THEN 'long' ELSE 'short' END AS side,
       n.holding, n.holding * n.book_size AS holding_usd, p.expected_move AS prior_expected_move
FROM named n
JOIN days d ON d.date = n.date
LEFT JOIN ledger p ON p.date = d.prior_date AND p.ticker = n.ticker
WHERE n.holding <> 0
ORDER BY n.date DESC, abs(n.holding) DESC, n.ticker;

-- The book after one open; with no argument, the latest. `FROM book_on(DATE '2026-11-17');`
CREATE OR REPLACE MACRO book_on(day := NULL) AS TABLE
SELECT * EXCLUDE (date) FROM book WHERE date = coalesce(day, (SELECT max(date) FROM ledger));

-- Per day, the book after the open: long and short weight, gross, net and the names on each side.
CREATE OR REPLACE VIEW exposure AS
SELECT date,
       sum(greatest(holding, 0)) AS long, sum(least(holding, 0)) AS short,
       sum(abs(holding)) AS gross, sum(holding) AS net,
       count(*) FILTER (holding > 0) AS names_long, count(*) FILTER (holding < 0) AS names_short
FROM ledger
GROUP BY date
ORDER BY date;

-- The book by day and sector.
CREATE OR REPLACE VIEW sector_exposure AS
SELECT date, sector,
       sum(greatest(holding, 0)) AS long, sum(least(holding, 0)) AS short,
       sum(holding) AS net, sum(abs(holding)) AS gross, count(*) AS names
FROM book
GROUP BY date, sector
ORDER BY date DESC, gross DESC, sector;

-- Every trade at an open and what it did to the name: open, close, flip, add or reduce.
CREATE OR REPLACE VIEW trades AS
SELECT date, ticker,
       CASE WHEN drifted = 0 AND holding <> 0 THEN 'open'
            WHEN drifted <> 0 AND holding = 0 THEN 'close'
            WHEN sign(drifted) * sign(holding) < 0 THEN 'flip'
            WHEN abs(holding) > abs(drifted) THEN 'add'
            ELSE 'reduce' END AS action,
       drifted, trade, holding, trade * book_size AS trade_usd
FROM ledger
WHERE trade <> 0
ORDER BY date DESC, abs(trade) DESC, ticker;

-- Per day in dollars: gross P&L, borrow, each cost, net as the daily note nets them, cumulative net, and
-- turnover, the weight traded.
CREATE OR REPLACE VIEW pnl AS
WITH days AS (
    SELECT date,
           sum(pnl) * any_value(book_size) AS gross_usd,
           sum(borrow) * any_value(book_size) AS borrow_usd,
           any_value(cost_spread) * any_value(book_size) AS cost_spread_usd,
           any_value(cost_impact) * any_value(book_size) AS cost_impact_usd,
           any_value(cost_commission) * any_value(book_size) AS cost_commission_usd,
           sum(abs(trade)) AS turnover
    FROM ledger
    GROUP BY date
)
SELECT date, gross_usd, borrow_usd, cost_spread_usd, cost_impact_usd, cost_commission_usd,
       gross_usd - borrow_usd - cost_spread_usd - cost_impact_usd - cost_commission_usd AS net_usd,
       sum(gross_usd - borrow_usd - cost_spread_usd - cost_impact_usd - cost_commission_usd) OVER (ORDER BY date) AS cumulative_net_usd,
       turnover
FROM days
ORDER BY date;

-- What each holding carried into a day earned and paid, for attribution: group it by ticker, sector or side.
-- Trading costs are charged by day, not by name, so they are in `pnl` and not here.
--     SELECT sector, sum(net_usd) AS net FROM earned GROUP BY ALL ORDER BY abs(net) DESC;
CREATE OR REPLACE VIEW earned AS
SELECT date, ticker, sector, CASE WHEN held > 0 THEN 'long' ELSE 'short' END AS side,
       pnl * book_size AS pnl_usd, borrow * book_size AS borrow_usd, (pnl - borrow) * book_size AS net_usd
FROM named
WHERE held <> 0;

-- One name day by day. `FROM history('SPY');`
CREATE OR REPLACE MACRO history(name) AS TABLE
SELECT date, held, ret, pnl, borrow, drifted, trade, holding, target, expected_move
FROM ledger
WHERE ticker = name
ORDER BY date;

-- The latest day's decision for the next open: each name's expected move beside its holding. Under the optimiser
-- `target` is null: it solves on the expected move at the next open, and its trades appear in the next ledger day.
CREATE OR REPLACE VIEW next_open AS
SELECT ticker, holding, expected_move, target
FROM ledger
WHERE date = (SELECT max(date) FROM ledger) AND (holding <> 0 OR isfinite(expected_move))
ORDER BY coalesce(expected_move, 0) DESC, ticker;

-- Every holding spell: a run of days a name is held on one side. `entry` is the open it was filled at, `exit` the
-- open it was closed or flipped at (null while open), `days` the opens it was held after.
CREATE OR REPLACE VIEW spells AS
WITH marked AS (
    SELECT *, sign(holding) AS side_sign,
           sign(holding) <> coalesce(lag(sign(holding)) OVER by_name, 0) AS starts,
           lead(date) OVER by_name AS next_date
    FROM ledger
    WINDOW by_name AS (PARTITION BY ticker ORDER BY date)
),
numbered AS (
    SELECT *, sum(starts::INTEGER) OVER (PARTITION BY ticker ORDER BY date) AS spell FROM marked
),
runs AS (
    SELECT ticker, spell, CASE WHEN any_value(side_sign) > 0 THEN 'long' ELSE 'short' END AS side,
           min(date) AS entry, max(date) AS last_day, count(*) AS days
    FROM numbered
    WHERE side_sign <> 0
    GROUP BY ticker, spell
),
carried AS (
    SELECT ticker, lag(spell) OVER (PARTITION BY ticker ORDER BY date) AS spell, held,
           pnl * book_size AS pnl_usd, borrow * book_size AS borrow_usd
    FROM numbered
),
paid AS (
    SELECT ticker, spell, sum(pnl_usd) AS pnl_usd, sum(borrow_usd) AS borrow_usd
    FROM carried
    WHERE held <> 0
    GROUP BY ticker, spell
)
SELECT r.ticker, r.side, r.entry, n.next_date AS exit, r.days,
       coalesce(p.pnl_usd, 0) AS pnl_usd, coalesce(p.borrow_usd, 0) AS borrow_usd
FROM runs r
JOIN numbered n ON n.ticker = r.ticker AND n.date = r.last_day
LEFT JOIN paid p ON p.ticker = r.ticker AND p.spell = r.spell
ORDER BY r.entry DESC, r.ticker;

-- Per day: the grid and the names carried in, the held names with no return, the optimiser's status, the slope,
-- and the code and snapshot the day ran on.
CREATE OR REPLACE VIEW health AS
SELECT date, count(*) AS names, count(*) FILTER (held <> 0) AS held,
       any_value(missing_returns) AS missing_returns, any_value(status) AS status, any_value(slope) AS slope,
       any_value(git_commit) AS git_commit, any_value(git_dirty) AS git_dirty, any_value(snapshot) AS snapshot,
       any_value(config_hash) AS config_hash
FROM ledger
GROUP BY date
ORDER BY date;

-- Each description fits the 56 characters an 80-column terminal leaves it, so the table does not wrap.
CREATE OR REPLACE VIEW guide AS
SELECT * FROM (VALUES
    ('ledger', 'every ledger day, as stored'),
    ('named', 'the ledger with each name''s sector on the day'),
    ('book', 'names held after each open, every day'),
    ('book_on()', 'the latest book; book_on(DATE ''...'') for one day'),
    ('exposure', 'long, short, gross, net and names, by day'),
    ('sector_exposure', 'the book by day and sector'),
    ('trades', 'every trade at an open: open, close, flip, add or reduce'),
    ('pnl', 'dollars by day: gross, borrow, costs, net, turnover'),
    ('earned', 'P&L and borrow by name and day, for attribution'),
    ('history(''TICKER'')', 'one name, day by day'),
    ('next_open', 'the expected moves behind the next open'),
    ('spells', 'holding spells: entry, exit, days, P&L'),
    ('health', 'by day: grid, missing returns, status, commit, snapshot'),
    ('sectors', 'the snapshot''s dated sectors')
) AS t(name, shows);

FROM guide;
