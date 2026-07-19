#!/usr/bin/env python3
"""
O-37 remediation: quarantine the 84 confirmed-synthetic geo/elec markets and
correct the trader-level fallout.

Background: two independent signals (a stats heuristic on duplicate/implausible
per-market trade stats, and a token-backfill failure sweep) converged on a
population of geo/elec markets containing fabricated trade tapes. A read-only
characterization + proof phase (2026-07-19) scoped and individually
live-verified against the Gamma/CLOB API a final set of 84 markets / 965,542
trades that do NOT exist on Polymarket, tracing to a single bulk-import event
on 2026-01-12/13 (+ a smaller 2026-04-01 secondary batch) with api_id IS NULL
across every row. Full arc: trading-swarm brain/decisions/2026-07-19-o37-synthetic-market-quarantine.md

Decision: quarantine, not delete. Reuses the existing markets.trade_gap_flag
exclusion mechanism (already honored by scripts/update_geo_elo.py and ~15
other call sites — zero code changes needed), paired with a new forensic-only
markets.flag_reason column so this quarantine is distinguishable from the
pre-existing Apr 7-18 trade-gap flagging.

This script is idempotent — safe to re-run. It has already been applied to
the live database (2026-07-19); it's checked in as the permanent, reviewable
record of exactly what was done, not as a script that still needs running.

Two-part remediation:
  1. Flag the 84 markets (trade_gap_flag=1, flag_reason=QUARANTINE_REASON).
  2. Bounded recompute for the 953 traders who ever traded in those markets:
     - Traders who still clear the 5-qualifying-trade floor without the
       flagged trades get a fresh geo_elo via the real production functions
       (scripts/update_geo_elo.py, unmodified) — 27 traders.
     - Traders who only cleared the floor BECAUSE of now-flagged trades are
       brought to the system's existing "hasn't qualified" representation —
       geo_elo/geo_elo_active/geo_directionality_score = NULL,
       geo_resolved_trades_count = the real remaining qualifying-market count
       (matching the convention already used for ~9,900 other never-qualified
       traders in the DB; no new sentinel invented) — 926 traders.

Proof phase found 0 cohort (geo_elo_active>=1800 AND geo_accuracy_pool=1 AND
research_excluded=0 AND bot_type IS NULL) and 0 Pool-C (geo_accuracy_pool=1)
exposure among the 953 — reconfirmed after this write. B1 is unaffected.
"""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import update_geo_elo as ug
import monitoring.column_definitions as cd

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'polymarket_tracker.db')

QUARANTINE_REASON = 'synthetic_quarantine_2026-07-19'

# The 84 confirmed-synthetic market_ids — individually live-verified absent
# from Polymarket via the Gamma/CLOB API (0% false positives on full
# re-verification). Explicit literal list, not a re-derived heuristic query,
# so this can never silently drift.
SYNTHETIC_MARKET_IDS = [
    '0x01d586e54bf8140b3ee4042422dc1ff6cc387d00bb2edd7d311ea3c58aedb1aa',
    '0x053514fdeb16b7510c0931ec99328dd08641e48c06aac4553f471928c1c1969b',
    '0x0744bd3c0f3521a76b9244d5f5bc04f58b71404cbd15b0940b269a25599a8ecd',
    '0x07e6232c82ca2237ad2c5beb78e597f27947636957f4ae9ddd4aa48ca59cda38',
    '0x08e61703a0151fb8b5cd3f589be989b56a1e5349ccfafcc05844a965e901ae9d',
    '0x0ff2f1a5e7b2584717605240f314d901aedf7d6c6b1b2a0dcfeb9f3a3348c4f4',
    '0x1188b08f33d226ae575732605f3e30308b8ad40cb6e8c203a5f90daf52851ca5',
    '0x120d0a5dda8f7d373bc424de162248b694a6561030e2f0b68d192fc43c6cf2a1',
    '0x14493caddec2b6f30ad2e4a1d60ba6fa86fdac85ec43217da35184e9b0f72a68',
    '0x1ac73a9335e804b42bd8c4b3a2e96193d7f2f9a2ad0d59747f614d51aebadfba',
    '0x221a2fbad5b7cff96818ce4f98aa5397554fb33a4dc4015125210b5d4ef5d039',
    '0x274712a7ffb97553a1367dbac473ca3e4cbfbdedfdca33bbf03ccda9722746b4',
    '0x2a1b37eecd1991cf9471a955d2c521e69cd235665652e26a7f9747b3554eeaac',
    '0x38c50c8a75a2e966d36c7936c63bba4e89552131b53a8ffb8a7b3ae912587cf9',
    '0x390df948a012677788a0faecba29a5458d52d91f6eb61d74033d0140a91cfae3',
    '0x3a0d7bb9e9f3101a54e556eb3472d034435b24e742da8ec0bc2fcd0b2f11f8fd',
    '0x3b42b75b772176235dc443e7dbdf53c20a584df4f4c5854abe3a1ee46a87bd4f',
    '0x3c6535ee9c36ac803cdd254490e856ae922a6194b431c9d0d4ecf0298774d05a',
    '0x3d834a88b5c0a418e3a042849d55ac95378002d6055a05893c7a52c146151981',
    '0x4bbf684ad2e3246f5052f8856cf47a170dbc639878fc5872230d95954bb53e6c',
    '0x4bd9afb5dd8e232ea5c98b24d621b3dc078344819fe420985dff1b8fe619ca3a',
    '0x4fe7c01242e8c10b0e8f1700830614a7f0f718dced251350fe503fe99459e6aa',
    '0x56435a47d7c1647583f6099a026ae36b6a3a43ff66c338c8bda92a615e6a6aae',
    '0x56e5a05fa617c143147949279c52f2912130ae2a045001f518eaa59fce147195',
    '0x5a5d8ccd830711fcf7e2f4b8e4a275d15cc9a90b48939acdf92fa11a45b220a8',
    '0x5c7eb37f83106aefbf2a035500ed5c15b3769c5c4e69428cd73c465e85b66400',
    '0x5e9b1c49278dfa6f082a3f8bf2eef3867b7cf81b64c249b02e1db3d8e432afdc',
    '0x614bd28803574df41228606d2812eac0d61e767da29b771ed40c7a11d921b77f',
    '0x63f0933d0e9b0ebc76f6d99bc953ce445cc43c70d5ca520f9ff5e1f861345368',
    '0x65412a88d22bfc268d3b35c94ba369a2fb443b79fa95545d5605e566cd76dc8d',
    '0x657195fda8c315771fe0cf25a1b60df207a9072688f73b96cf17a890ce7ab753',
    '0x69c2d75531bac1149ef10e0ef761c8e1b4e0c2e7462d439df275d733d1a7424a',
    '0x6f00d45f8cff0d327b389c0db15e613720d6f73d354f37a9f8caca316feca3bb',
    '0x70c7e5eea60d54995a2292ae0254f8734d4edfa34f1904e3daa7f3020a5fd5e0',
    '0x73570416f406878cf2f9529646d060a0566cee2222b60ea8cc2cde55f0144bf6',
    '0x772d625251118968975cb2952f9cd105a734caebe2e5d41e34e27b5bfe4e85b5',
    '0x7999127b94509a3f44db2d0ee2819deaba36d638841ca30f30aa40d443b67030',
    '0x7b50deb091ddc557892d6f6c47bd99b75c82ec1ac0cc3777a626aed49780ca21',
    '0x7cc821cd883cf05e4a1756ec7de9dae8910ac9700defe792e4f93fc67ba56706',
    '0x8724a8146132863579720760f1e89b1f93b81cb2698a7f17a47d876055c40507',
    '0x88922399ae90dfec9abe74836e3edc08a33a3987736ea03696ee7a9778203bec',
    '0x8a50ec0c041037d0b5141dd9438e35044d1a4798927983da30a74a25c96704a7',
    '0x8bdc6b9e14f84918c6bcf257a44688358947fd6160766bb6a62c872b788a7cc3',
    '0x8c329a8ab91e9b5117fee413844e40308a24ba54f35ad507286479424dc412ad',
    '0x8cf307f4a7f70abac3d673b295be067481d8ea522071226cfb16be8a8fc1e04d',
    '0x8ff3cb7c76ab1fe007c06b1525b6f8e79859c7bdeffc505dc074ed5a8efbc7f3',
    '0x90aaa42579479ec078e087d5b6a191b20c2ff7044b24e6552fd6612bb4460efd',
    '0x9175579968d0ac4976de454f0c81e6b3e63c1ea14252b3d0d6498fe6e9c9e6a1',
    '0x935361e70de6718372938252bccebc195a34303f824d3444dbaf9ec930d25da6',
    '0x97dbedfee53533ae8d22238e8500d5a8b2848e0fe4681648d132f3251c3e0df3',
    '0x9c9f5fbb361b92513826f2866428c7dd9dc3f16dab964ffed1771dde7c78ec85',
    '0x9e4cfab729aa6030759ff3ccd3df87be97a5635c98eaa4a3a4669d9c25afa90e',
    '0x9f42c004c1aae5d3932e3658db52353b91c76621f4fa45753b2fedddb615440c',
    '0xa52c46cc6d6e0fcc3ed045151bb2f765de844af96d27211be48b9df96c251395',
    '0xa6cdba9bc408b6477abdec6bf56be1eb3bb07bc83845feae0920122cf7ef801a',
    '0xa9216ba7da3e7ba29bc59aafd7f06bb87647facf0555b7509859e1dd0e082ecf',
    '0xb616705ee513580f1b907bef92e5fa74ceb9788785b8be0eeda898c942b7c11c',
    '0xb79500945f6d7f0dbe7ab2e9b748f30dc971f30efe48976e0c14898c55ad4112',
    '0xb80969a7dab0b73264434a160e7de869d3521fa4393fb3bdf180003a7d783dd2',
    '0xba136f2232685ceeccbe10b7e9512302ef6d83d6720635c792f472399979545a',
    '0xbb1210f8abeb1a4327877abc3fd9d9cdd3e1684a5237fc5be452e09ca64d7b91',
    '0xbd6df7472a2f2f3bb6cbbef3902e0a8a9f86d8941c1a0086dfe8f7af5722c352',
    '0xbe9e42d2af047cf59d65a9a6a0b6114256acca041b827aa6b726bbe0612d3781',
    '0xc6575982acd0aaa053762392ec9ac0308329875135ec2abcf787c663a2b2899c',
    '0xc8807f8d1e825aa7ee6b14b2f12880f3ee054913ac1ba7b35015c1cbe38aa346',
    '0xc96283d1f00365ba2fd61cc3f7fdbc319183964a8d0b5013b120e6ee2a35835a',
    '0xcea545cb61b9c17893cd83e360655aa0be153b193be73831e2e45aa45ee51e23',
    '0xcf98445e1dd4ce463ccb65e076edc05f8d18c482458ab7eae0069e067dc29057',
    '0xcf9d3f052e25d2e839b8c14f89200cda0849478fdaa3f644f6f2bfac0074210b',
    '0xcffe00b96c49b84e518ea9171449573170b20ee3f67822d4befc4b75b591753c',
    '0xd28517308e1e437669dcef0e6de914bc6bc5fe65926faaf3046b0c1be6feaf2e',
    '0xd81d41fce13cf19021d62bc513faffb33ff79601aaa83692803153fa256464f2',
    '0xd85af6b4892bba69c0c1e39955433ad66fc6a1a35eaec9a4539330081e9fb552',
    '0xdb74379d5cbc304024f63abafebc3e18aa512510b49552c86211805e06cd9eb6',
    '0xdd4892d09b03d40722101a8d57b44ccb7bf11a73f0fd98fdad88a47e08ddf67e',
    '0xdf1cd95520ca1c24f3d17e9d85007fa2ebde4c81df61d1ba80c34ddd37e72970',
    '0xdf31a15ee2f55b675d44882cbb2053a72b83ad40eef5d60b11762517f695f4ba',
    '0xe67a01e8ce4d2445b020f23a5e0bbbd54418defa84df033f8c67de2cdca160cc',
    '0xe6edcf2b565be06acbf8f87a1947c9cfce167b3f303c3ecb21df91e8fe36a30f',
    '0xebdca20fc96a77325b4e5b3369357688d2249deb1a42d5c4b746811ab6ac8335',
    '0xf18908407e80f1f4e9c8cf5f1fe26e0c3f7d4e92b1bd5e19a9165fd9b0255e91',
    '0xf37393417fa9843b17a395b4a3483a26ed7969abfb409703cda454e94d820981',
    '0xf5200c714aa94c943675bf57af213c9afbc1343c87ed92e0b7b8df42cc83a30f',
    '0xff1c71131848e302dacb5739a9189c1ffdf711506866499f473f0a568e861f74',
]


def flag_markets(conn):
    try:
        conn.execute("ALTER TABLE markets ADD COLUMN flag_reason TEXT")
    except sqlite3.OperationalError:
        pass

    placeholders = ",".join("?" for _ in SYNTHETIC_MARKET_IDS)
    with conn:
        cur = conn.execute(
            f"UPDATE markets SET trade_gap_flag = 1, flag_reason = ? "
            f"WHERE market_id IN ({placeholders})",
            (QUARANTINE_REASON, *SYNTHETIC_MARKET_IDS)
        )
    print(f"[O-37] Flagged {cur.rowcount} markets (expected 84)")


def _affected_traders(conn):
    placeholders = ",".join("?" for _ in SYNTHETIC_MARKET_IDS)
    rows = conn.execute(
        f"SELECT DISTINCT trader_address FROM trades WHERE market_id IN ({placeholders})",
        SYNTHETIC_MARKET_IDS
    ).fetchall()
    return [r[0] for r in rows]


def recompute_affected_traders(conn):
    addresses = _affected_traders(conn)
    print(f"[O-37] Affected traders: {len(addresses)} (expected 953)")

    recompute_updates = []
    sub_floor_addresses = []
    for address in addresses:
        trades = ug._fetch_qualifying_trades(conn, address)
        if len(trades) < ug.MIN_TRADES_FOR_ELO:
            sub_floor_addresses.append(address)
            continue
        geo_elo = ug._compute_geo_elo(trades)
        directionality = ug._compute_geo_directionality(trades)
        last_any_trade = conn.execute("""
            SELECT MAX(tr.timestamp)
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            WHERE tr.trader_address = ?
            AND tr.market_category IN ('Geopolitics', 'Elections')
            AND tr.timestamp <= datetime('now')
        """, (address,)).fetchone()[0]
        geo_elo_active = cd.compute_geo_elo_active(geo_elo, last_any_trade)
        canonical_count = conn.execute("""
            SELECT COUNT(DISTINCT tr.market_id)
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            WHERE tr.trader_address = ?
              AND tr.trade_result IN ('won', 'lost')
              AND m.category IN ('Geopolitics', 'Elections')
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
        """, (address,)).fetchone()[0]
        recompute_updates.append((geo_elo, directionality, canonical_count, geo_elo_active, address))

    with conn:
        conn.executemany("""
            UPDATE traders
            SET geo_elo                   = ?,
                geo_directionality_score  = ?,
                geo_resolved_trades_count = ?,
                geo_elo_active            = ?
            WHERE address = ?
        """, recompute_updates)
    print(f"[O-37] Recomputed (cleared floor without flagged trades): {len(recompute_updates)}")

    # Sub-floor correction: matches the system's existing representation for
    # any trader who hasn't cleared the qualifying floor (empirically
    # confirmed convention: geo_elo/geo_elo_active/geo_directionality_score
    # = NULL, geo_resolved_trades_count = real current count).
    if sub_floor_addresses:
        with conn:
            for address in sub_floor_addresses:
                conn.execute("""
                    UPDATE traders
                    SET geo_elo = NULL,
                        geo_elo_active = NULL,
                        geo_directionality_score = NULL,
                        geo_resolved_trades_count = (
                          SELECT COUNT(DISTINCT tr.market_id)
                          FROM trades tr JOIN markets m ON m.market_id = tr.market_id
                          WHERE tr.trader_address = traders.address
                            AND tr.trade_result IN ('won','lost')
                            AND m.category IN ('Geopolitics','Elections')
                            AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
                        )
                    WHERE address = ?
                """, (address,))
    print(f"[O-37] Brought to sub-floor representation: {len(sub_floor_addresses)} (expected 926)")

    _evicted, pool_c = cd.refresh_pool_c(conn)
    print(f"[O-37] Pool C after recompute: {pool_c}")


def main():
    conn = ug._get_connection()
    flag_markets(conn)
    recompute_affected_traders(conn)
    conn.close()
    print("[O-37] Done.")


if __name__ == "__main__":
    main()
