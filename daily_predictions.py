def get_player_full_details(league_id, player_id, headers):
    resp = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/players/{player_id}", headers)
    if not resp or resp.status_code != 200:
        return 0, 0, 0, ""
    
    p = resp.json()
    
    # EINMALIGER DEBUG-PRINT: Zeigt uns die echte Struktur im GitHub Actions Log
    if player_id:
        print(f"=== DEBUG PLAYER JSON ({p.get('n', 'Spieler')}) ===")
        print(p)
        print("================================================")
    
    mv = p.get("mv") or 0
    team_name = p.get("tn") or ""
    change = p.get("mvc") or 0
    pred_target = int(change * 0.92) if change > 0 else 0
    
    return mv, change, pred_target, team_name
