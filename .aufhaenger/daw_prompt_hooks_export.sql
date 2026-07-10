-- DAW prompt hooks export
-- exported_at: 2026-07-09T23:27:12+00:00
-- count: 52
-- Import: sqlite3 suno_fastapi_app.db < .aufhaenger/daw_prompt_hooks_export.sql
BEGIN TRANSACTION;
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook + Übergang doppeln';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook + Übergang doppeln', 'Setze die erste Hook doppelt und berücksichtige dabei den Übergangsauftakt nach der Hook.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Taktgrenzen. Bestimme nicht nur den eigentlichen Hook-Bereich, sondern auch den direkt nachfolgenden musikalischen Übergangsauftakt zum nächsten Verse, falls dieser rhythmisch oder musikalisch noch zur Hook-Phrase gehört.

Kopiere den Bereich vom Hook-Start bis einschließlich des Übergangsauftakts nach der Hook und füge ihn direkt danach erneut ein. Der nächste Verse soll erst nach der zweiten Kopie des Übergangsauftakts beginnen.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verdoppelt die erste Hook inklusive nachfolgendem Übergangsauftakt zum nächsten Verse.', 'daw', '["importiert", "Bereits definierte Hook-Prompts"]', 1, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Bereits definierte Hook-Prompts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook doppeln, Übergang behalten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook doppeln, Übergang behalten', 'Setze die erste Hook doppelt, aber lasse den Übergangsauftakt zum nächsten Verse nur einmal stehen.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Taktgrenzen. Bestimme das Ende der eigentlichen Hook vor dem nachfolgenden Übergangsauftakt. Kopiere nur den reinen Hook-Bereich und füge ihn direkt vor dem bestehenden Übergangsauftakt ein.

Der Ablauf soll danach sein: erste Hook, kopierte Hook, bestehender Übergangsauftakt, nächster Verse.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Der Übergangsauftakt darf nicht mitkopiert werden, wenn er eindeutig in den nächsten Verse hineinführt. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verdoppelt nur die erste Hook und lässt den bestehenden Übergangsauftakt einmal vor dem nächsten Verse stehen.', 'daw', '["importiert", "Bereits definierte Hook-Prompts"]', 2, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Bereits definierte Hook-Prompts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook 4 Takte doppeln';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook 4 Takte doppeln', 'Verdopple die erste Hook. Nutze dafür ausschließlich die ersten 4 vollständigen Takte der ersten Hook.

Erkenne den Start der ersten Hook anhand der Lyrics-/SRT-Struktur und der BeatNet+-Downbeats. Schneide ab dem ersten vollständigen Hook-Takt exakt 4 Takte lang. Kopiere diese 4 Takte und füge sie direkt danach erneut ein.

Falls nach der Hook ein Übergangsauftakt in den nächsten Verse folgt, darf dieser nicht mitkopiert werden. Der Ablauf soll danach sein: erste 4 Hook-Takte, kopierte 4 Hook-Takte, danach der bestehende weitere Songverlauf.', 'Verdoppelt ausschließlich die ersten 4 vollständigen Takte der ersten Hook.', 'daw', '["importiert", "Bereits definierte Hook-Prompts"]', 3, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Bereits definierte Hook-Prompts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook auf 8 Takte verlängern';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook auf 8 Takte verlängern', 'Verlängere die erste Hook auf 8 Takte.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme den Start der Hook exakt auf der ersten vollständigen Hook-Taktgrenze. Nutze die ersten 4 vollständigen Hook-Takte als Quellbereich, kopiere sie und füge sie direkt danach erneut ein, sodass die Hook anschließend 8 vollständige Takte umfasst.

Falls nach der Hook ein Übergang oder Auftakt zum nächsten Verse folgt, lasse diesen Übergang nur einmal nach der verlängerten Hook stehen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verlängert eine 4-Takt-Hook durch Duplikation auf 8 Takte.', 'daw', '["importiert", "Hook / Refrain"]', 4, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Hook / Refrain", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook-Ende sauber setzen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook-Ende sauber setzen', 'Setze das Ende der ersten Hook sauber auf eine musikalisch passende Taktgrenze.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme, wo der eigentliche Hook-Inhalt endet, und verschiebe das Hook-Ende auf die nächste saubere Downbeat- oder Bar-Grenze, ohne Wörter, Adlibs, Fills oder Übergänge unnatürlich abzuschneiden.

Der bestehende Songverlauf soll musikalisch flüssig bleiben. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Schneidet das Hook-Ende exakt auf die nächste Taktgrenze.', 'daw', '["importiert", "Hook / Refrain"]', 5, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Hook / Refrain", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Letzte Hook verlängern';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Letzte Hook verlängern', 'Verlängere die letzte Hook des Songs.

Erkenne die letzte Hook anhand der Lyrics-/SRT-Struktur, wiederholter Hook-Zeilen und BeatNet+-Taktgrenzen. Bestimme einen musikalisch vollständigen Hook-Bereich und dupliziere ihn direkt vor dem Outro oder Songende, sodass der finale Refrain länger und wirkungsvoller wird.

Achte darauf, vorhandene Outro-Übergänge, Schlussfills und Fade-Outs nicht unnötig zu beschädigen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Macht den finalen Refrain länger und epischer.', 'daw', '["importiert", "Hook / Refrain"]', 6, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Hook / Refrain", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook vorziehen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook vorziehen', 'Ziehe die erste Hook im Arrangement früher nach vorne.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme einen passenden früheren Einfügepunkt auf einer vollständigen Taktgrenze, idealerweise nach einem sinnvollen Verse- oder Intro-Ende. Verschiebe oder kopiere die Hook so, dass sie früher im Song erscheint und der Ablauf musikalisch schlüssig bleibt.

Bestehende Übergänge sollen erhalten oder sauber angepasst werden. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verschiebt die erste Hook früher in den Song.', 'daw', '["importiert", "Hook / Refrain"]', 7, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Hook / Refrain", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook wiederholen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook wiederholen', 'Füge die erste Hook später im Song erneut ein.

Erkenne die erste vollständige Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kopiere den vollständigen Hook-Bereich taktgenau und füge ihn an einer musikalisch sinnvollen späteren Stelle erneut ein, zum Beispiel nach Verse 2 oder vor dem Outro.

Achte darauf, Übergänge, Auftakte und vorhandene Songstruktur sauber zu erhalten. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Fügt die erste Hook später im Song erneut ein.', 'daw', '["importiert", "Hook / Refrain"]', 8, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Hook / Refrain", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook ohne Übergang doppeln';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook ohne Übergang doppeln', 'Verdopple die erste Hook ohne nachfolgenden Übergang.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme nur den reinen Hook-Bereich vom ersten vollständigen Hook-Takt bis zum Ende der letzten vollständigen Hook-Phrase. Kopiere keine nachfolgenden Drumfills, Turnarounds, Adlibs oder Auftakte zum nächsten Verse mit.

Füge die kopierte Hook direkt nach dem reinen Hook-Bereich ein. Der bestehende Übergang zum nächsten Abschnitt soll danach nur einmal stehen bleiben. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verdoppelt die Hook ohne Intro-, Fill- oder Verse-Übergang.', 'daw', '["importiert", "Hook / Refrain"]', 9, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Hook / Refrain", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Verse doppeln';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Verse doppeln', 'Verdopple den ersten vollständigen Verse.

Erkenne den ersten Verse anhand der Lyrics-/SRT-Struktur, Vocal-Einsätze und BeatNet+-Downbeats. Bestimme den vollständigen Verse-Bereich von der ersten Verse-Taktgrenze bis zur letzten vollständigen Verse-Taktgrenze vor Hook, Bridge oder Übergang. Kopiere diesen Bereich und füge ihn direkt danach erneut ein.

Achte darauf, dass Übergänge zur Hook nicht doppelt oder unnatürlich abgeschnitten werden. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Dupliziert den ersten vollständigen Verse taktgenau.', 'daw', '["importiert", "Verse / Parts"]', 10, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Verse / Parts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Verse kürzen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Verse kürzen', 'Kürze den ersten Verse taktgenau.

Erkenne den ersten Verse anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Entferne musikalisch sinnvolle vollständige Takte aus dem Verse, ohne Wörter, Reimphrasen oder Übergänge unnatürlich abzuschneiden. Bevorzuge Bereiche mit Wiederholungen, Pausen oder weniger wichtigen Zeilen.

Verbinde den verbleibenden Verse sauber mit dem nachfolgenden Abschnitt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Entfernt ausgewählte Takte aus einem Verse.', 'daw', '["importiert", "Verse / Parts"]', 11, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Verse / Parts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Verse austauschen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Verse austauschen', 'Tausche einen Verse-Bereich gegen einen anderen passenden Songabschnitt aus.

Erkenne den Ziel-Verse anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme einen gleich langen oder musikalisch kompatiblen Ersatzbereich aus dem Song. Entferne den Zielbereich und setze den Ersatzbereich an dessen Position ein.

Achte auf Taktlänge, Downbeats, Übergänge, Vocal-Einsätze und saubere Anschlussstellen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Ersetzt einen Verse-Bereich durch einen anderen Songabschnitt.', 'daw', '["importiert", "Verse / Parts"]', 12, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Verse / Parts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Verse 2 früher starten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Verse 2 früher starten', 'Lasse Verse 2 früher starten.

Erkenne den Start von Verse 2 anhand der Lyrics-/SRT-Struktur, Vocal-Einsätze und BeatNet+-Downbeats. Bestimme den Bereich direkt vor Verse 2, der entfernt oder gekürzt werden kann, zum Beispiel überlange Pausen, Wiederholungen, Fills oder unnötige Zwischenparts.

Entferne diesen Bereich taktgenau, sodass Verse 2 früher startet und musikalisch sauber an den vorherigen Abschnitt anschließt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Entfernt Zwischenraum vor Verse 2 und setzt ihn früher.', 'daw', '["importiert", "Verse / Parts"]', 13, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Verse / Parts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = '16 Takte extrahieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('16 Takte extrahieren', 'Extrahiere exakt 16 vollständige Takte aus dem gewünschten Abschnitt.

Erkenne den Start des relevanten Abschnitts anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Schneide ab der ersten passenden vollständigen Taktgrenze exakt 16 Takte heraus. Der extrahierte Bereich soll als eigener Clip oder neue Variante gespeichert werden.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Vermeide abgeschnittene Wörter, unvollständige Vocal-Phrasen und halbe Übergänge. Arbeite non-destruktiv.', 'Schneidet exakt 16 Takte ab gewähltem Abschnitt heraus.', 'daw', '["importiert", "Verse / Parts"]', 14, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Verse / Parts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Part loopen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Part loopen', 'Erstelle einen sauberen Loop aus dem gewählten Part.

Erkenne den gewünschten Part anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme Start und Ende so, dass der Bereich auf vollständigen Taktgrenzen liegt und beim Wiederholen rhythmisch sauber zurück auf den Anfang springt. Kopiere den Bereich und wiederhole ihn in der gewünschten Länge.

Achte auf Downbeat-Konsistenz, saubere Loop-Enden und natürliche Übergänge. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Loopt einen Verse-, Hook- oder Instrumentalabschnitt sauber auf Bar-Grenzen.', 'daw', '["importiert", "Verse / Parts"]', 15, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Verse / Parts", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Intro kürzen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Intro kürzen', 'Kürze das Intro des Songs.

Erkenne das Intro anhand der Lyrics-/SRT-Struktur, des ersten Vocal-Einsatzes und BeatNet+-Downbeats. Entferne überflüssige vollständige Intro-Takte vor dem ersten wichtigen Einsatz, ohne den musikalischen Einstieg unnatürlich abzuschneiden.

Der Song soll danach schneller und direkter starten. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Entfernt überflüssige Intro-Takte vor dem ersten Einsatz.', 'daw', '["importiert", "Intro / Outro"]', 16, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Intro / Outro", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Intro verlängern';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Intro verlängern', 'Verlängere das Intro des Songs.

Erkenne das Intro anhand der Lyrics-/SRT-Struktur, BeatNet+-Downbeats und des ersten Vocal-Einsatzes. Wähle einen musikalisch sauberen Intro-Bereich von vollständigen Takten, kopiere ihn und füge ihn vor dem ersten Einsatz erneut ein, sodass der Einstieg länger wirkt.

Achte darauf, dass der erste Vocal-Einsatz weiterhin sauber auf einer passenden Taktgrenze beginnt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Dupliziert Intro-Takte für längeren Einstieg.', 'daw', '["importiert", "Intro / Outro"]', 17, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Intro / Outro", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Direkt zur Hook starten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Direkt zur Hook starten', 'Erstelle eine Version, die direkt mit der ersten Hook startet.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Entferne alle vorherigen Bereiche bis zum Start der ersten vollständigen Hook oder bis zu einem musikalisch passenden Auftakt unmittelbar vor der Hook.

Der neue Songstart soll sauber, druckvoll und nicht abgeschnitten wirken. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Entfernt Intro/Verse-Anfang und startet beim ersten Refrain.', 'daw', '["importiert", "Intro / Outro"]', 18, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Intro / Outro", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Outro verlängern';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Outro verlängern', 'Verlängere das Outro des Songs.

Erkenne das Outro oder die letzten musikalisch vollständigen Takte anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kopiere einen passenden Schlussbereich und füge ihn vor dem endgültigen Ende erneut ein, sodass das Outro länger wirkt.

Achte darauf, dass ein vorhandener Schlussakzent oder Fade-Out nicht unnatürlich doppelt erscheint. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Wiederholt die letzten Takte für ein längeres Outro.', 'daw', '["importiert", "Intro / Outro"]', 19, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Intro / Outro", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Fade-Out setzen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Fade-Out setzen', 'Setze ein sauberes Fade-Out am Songende.

Erkenne das musikalische Ende anhand der letzten vollständigen Taktgrenzen und BeatNet+-Downbeats. Lege den Fade-Out so an, dass er musikalisch natürlich beginnt und auf dem Songende sauber ausläuft. Schneide bei Bedarf das Ende auf die nächste passende Taktgrenze.

Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Erstellt ein sauberes Fade-Out am Songende.', 'daw', '["importiert", "Intro / Outro"]', 20, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Intro / Outro", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Outro abschneiden';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Outro abschneiden', 'Schneide das Outro nach der letzten sinnvollen vollständigen Taktgrenze ab.

Erkenne das Ende des musikalisch relevanten Songs anhand der Lyrics-/SRT-Struktur, BeatNet+-Downbeats und des letzten klaren musikalischen Abschlusses. Entferne überlange Ausläufe, Pausen oder unnötige Wiederholungen nach diesem Punkt.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Setze bei Bedarf ein kurzes sauberes Fade-Out. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Schneidet den Song nach der letzten vollständigen Taktgrenze ab.', 'daw', '["importiert", "Intro / Outro"]', 21, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Intro / Outro", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Übergang behalten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Übergang behalten', 'Behalte den bestehenden Übergang zum nächsten Part nur einmal.

Erkenne den zu bearbeitenden Abschnitt und den nachfolgenden Übergang anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Wenn der Abschnitt dupliziert oder verlängert wird, kopiere den Übergang nicht mit. Der bestehende Übergang soll nach der Kopie weiterhin genau einmal direkt vor dem nächsten Part stehen.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Lässt einen bestehenden Übergang nur einmal vor dem nächsten Part stehen.', 'daw', '["importiert", "Übergänge / Fills / Auftakte"]', 22, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Übergänge / Fills / Auftakte", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Übergang doppeln';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Übergang doppeln', 'Dopple den Abschnitt inklusive nachfolgendem Übergang.

Erkenne den gewünschten Abschnitt und den direkt folgenden musikalischen Übergang anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Wenn der Übergang rhythmisch oder musikalisch noch zur Phrase gehört, kopiere den Abschnitt inklusive dieses Übergangs und füge ihn direkt danach erneut ein.

Der nächste Songabschnitt soll erst nach der zweiten Kopie des Übergangs beginnen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Kopiert Hook plus nachfolgenden Übergangsauftakt gemeinsam.', 'daw', '["importiert", "Übergänge / Fills / Auftakte"]', 23, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Übergänge / Fills / Auftakte", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Fill isolieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Fill isolieren', 'Isoliere den markanten Fill oder Turnaround als eigenen Bereich.

Erkenne den Fill anhand von BeatNet+-Downbeats, auffälligen rhythmischen Änderungen und der Position zwischen zwei Songabschnitten. Schneide den Fill von der vorherigen passenden Taktgrenze bis zur nachfolgenden passenden Taktgrenze als eigenen Clip heraus.

Der Fill soll später wieder sauber vor Hooks, Verses oder Breaks eingefügt werden können. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv.', 'Schneidet einen Drumfill oder Turnaround als eigenen Bereich heraus.', 'daw', '["importiert", "Übergänge / Fills / Auftakte"]', 24, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Übergänge / Fills / Auftakte", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Fill vor Hook setzen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Fill vor Hook setzen', 'Setze einen vorhandenen Fill direkt vor die erste Hook.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Suche einen passenden vorhandenen Drumfill oder Turnaround im Song, kopiere ihn taktgenau und füge ihn unmittelbar vor dem Hook-Start ein.

Achte darauf, dass der Hook-Start weiterhin sauber auf dem Downbeat liegt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Fügt einen vorhandenen Übergangsfill direkt vor die Hook.', 'daw', '["importiert", "Übergänge / Fills / Auftakte"]', 25, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Übergänge / Fills / Auftakte", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Auftakt erkennen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Auftakt erkennen', 'Erkenne den musikalischen Auftakt eines Abschnitts.

Analysiere Lyrics-/SRT-Struktur, BeatNet+-Downbeats, Vocal-Einsätze, Drumfills, Adlibs und musikalische Lead-ins. Bestimme, ob der Auftakt vor dem Abschnitt liegt, nach dem Abschnitt in den nächsten Part führt oder als eigenständiger Übergang behandelt werden sollte.

Gib Start und Ende des Auftakts taktgenau an und beschreibe, ob er beim Duplizieren mitkopiert oder nur einmal stehen bleiben soll. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen.', 'Findet musikalische Lead-ins vor oder nach einem Abschnitt.', 'daw', '["importiert", "Übergänge / Fills / Auftakte"]', 26, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Übergänge / Fills / Auftakte", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Übergang glätten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Übergang glätten', 'Glätte den Übergang zwischen zwei geschnittenen Songabschnitten.

Analysiere die Schnittstelle anhand von BeatNet+-Downbeats, Taktgrenzen, Vocal-Phrasen und vorhandenen Fills. Verschiebe Start- und Endpunkte so, dass der Übergang rhythmisch stabil, musikalisch sauber und ohne hörbare Stolperstelle funktioniert.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Nutze bei Bedarf minimale Fades, aber vermeide unnötige Klangveränderungen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verschiebt Schnittpunkte auf passende Beat-/Taktgrenzen.', 'daw', '["importiert", "Übergänge / Fills / Auftakte"]', 27, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Übergänge / Fills / Auftakte", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Songstruktur analysieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Songstruktur analysieren', 'Analysiere die vollständige Songstruktur.

Erkenne anhand von Lyrics-/SRT-Struktur, wiederholten Textzeilen, Vocal-Einsätzen und BeatNet+-Downbeats die wichtigsten Abschnitte des Songs: Intro, Verse, Hook, Bridge, Break, Outro und Übergänge. Gib für jeden Abschnitt Start, Ende, geschätzte Taktanzahl und kurze Begründung aus.

Schneide noch nichts. Erzeuge nur eine strukturierte Analyse, die als Grundlage für spätere non-destruktive Bearbeitung verwendet werden kann.', 'Erkennt Intro, Verse, Hook, Bridge und Outro anhand von Lyrics/SRT/Beats.', 'daw', '["importiert", "Arrangement / Struktur"]', 28, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Arrangement / Struktur", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Arrangement verdichten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Arrangement verdichten', 'Verdichte das Arrangement des Songs.

Analysiere die Songstruktur anhand von Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Suche überlange Pausen, unnötige Wiederholungen, zu lange Intros, zu lange Outros oder Zwischenparts ohne klare Funktion. Entferne oder kürze nur vollständige musikalische Takte, damit der Song direkter und kompakter wirkt.

Achte darauf, Hooks, wichtige Verse-Zeilen, Übergänge und musikalische Höhepunkte zu erhalten. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Entfernt lange Pausen, Wiederholungen oder unnötige Zwischenparts.', 'daw', '["importiert", "Arrangement / Struktur"]', 29, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Arrangement / Struktur", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Radioversion erstellen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Radioversion erstellen', 'Erstelle eine kompakte Radioversion des Songs.

Analysiere Intro, Verse, Hook, Bridge, Outro und Wiederholungen anhand von Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kürze den Song auf eine straffere Version, indem du überlange Intros, doppelte Hooks, unnötige Bridges oder zu lange Outros reduzierst.

Die wichtigsten Songteile sollen erhalten bleiben. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Kürzt den Song auf eine kompaktere Version.', 'daw', '["importiert", "Arrangement / Struktur"]', 30, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Arrangement / Struktur", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Extended Version erstellen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Extended Version erstellen', 'Erstelle eine Extended Version des Songs.

Analysiere die Songstruktur anhand von Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Verlängere musikalisch sinnvolle Bereiche wie Intro, Hook, Break oder Outro durch taktgenaue Duplikation. Die neue Version soll länger wirken, ohne künstlich oder unruhig zu klingen.

Achte auf saubere Übergänge, Downbeats und vollständige Phrasen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verlängert Hook-, Intro- oder Outro-Bereiche.', 'daw', '["importiert", "Arrangement / Struktur"]', 31, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Arrangement / Struktur", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Bridge entfernen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Bridge entfernen', 'Entferne die Bridge aus dem Song.

Erkenne die Bridge anhand der Lyrics-/SRT-Struktur, musikalischer Änderung und BeatNet+-Downbeats. Entferne den vollständigen Bridge-Bereich taktgenau und verbinde den vorherigen Abschnitt sauber mit dem nachfolgenden Abschnitt.

Achte darauf, dass der Übergang rhythmisch und musikalisch schlüssig bleibt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Entfernt einen Mittelteil und verbindet Hook/Verse sauber.', 'daw', '["importiert", "Arrangement / Struktur"]', 32, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Arrangement / Struktur", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Neue Hook nach Verse 2';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Neue Hook nach Verse 2', 'Füge nach Verse 2 eine zusätzliche Hook ein.

Erkenne Verse 2 und die erste vollständige Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kopiere die Hook taktgenau und füge sie direkt nach Verse 2 oder nach dem dortigen Übergang ein, je nachdem was musikalisch sauberer ist.

Achte darauf, dass der neue Hook-Einsatz auf einer vollständigen Downbeat-/Taktgrenze beginnt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Fügt eine vorhandene Hook nach dem zweiten Verse ein.', 'daw', '["importiert", "Arrangement / Struktur"]', 33, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Arrangement / Struktur", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Auf Takt schneiden';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Auf Takt schneiden', 'Schneide den gewünschten Bereich exakt auf Taktgrenzen.

Nutze BeatNet+-Downbeats als verbindliche rhythmische Referenz. Verschiebe Start und Ende des gewählten Bereichs auf die nächstliegenden musikalisch sinnvollen Downbeat- oder Bar-Grenzen. Vermeide Schnitte mitten in Wörtern, Vocal-Phrasen, Fills oder wichtigen Transienten.

Arbeite ausschließlich beat-, downbeat- und taktgenau. Speichere das Ergebnis non-destruktiv als neue editierte Variante.', 'Schneidet einen Bereich exakt auf Downbeat-/Bar-Grenzen.', 'daw', '["importiert", "Beat-/Taktgenaues Schneiden"]', 34, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Beat-/Taktgenaues Schneiden", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = '4 Takte kopieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('4 Takte kopieren', 'Kopiere exakt 4 vollständige Takte ab dem gewählten Abschnittsstart.

Erkenne den Abschnittsstart anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Setze den Start auf die erste passende vollständige Taktgrenze und kopiere exakt 4 vollständige Takte. Füge den kopierten Bereich direkt nach dem Originalbereich oder an der gewünschten Zielposition ein.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Kopiert exakt 4 vollständige Takte ab Abschnittsstart.', 'daw', '["importiert", "Beat-/Taktgenaues Schneiden"]', 35, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Beat-/Taktgenaues Schneiden", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = '8 Takte kopieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('8 Takte kopieren', 'Kopiere exakt 8 vollständige Takte ab dem gewählten Abschnittsstart.

Erkenne den Abschnittsstart anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Setze den Start auf die erste passende vollständige Taktgrenze und kopiere exakt 8 vollständige Takte. Füge den kopierten Bereich direkt nach dem Originalbereich oder an der gewünschten Zielposition ein.

Achte darauf, keine Übergänge mitzunehmen, sofern sie nicht ausdrücklich Teil des Bereichs sein sollen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Kopiert exakt 8 vollständige Takte ab Abschnittsstart.', 'daw', '["importiert", "Beat-/Taktgenaues Schneiden"]', 36, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Beat-/Taktgenaues Schneiden", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = '16 Takte kopieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('16 Takte kopieren', 'Kopiere exakt 16 vollständige Takte ab dem gewählten Abschnittsstart.

Erkenne den Abschnittsstart anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Setze den Start auf die erste passende vollständige Taktgrenze und kopiere exakt 16 vollständige Takte. Füge den kopierten Bereich direkt nach dem Originalbereich oder an der gewünschten Zielposition ein.

Der Bereich soll als vollständiger musikalischer Part funktionieren. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Kopiert exakt 16 vollständige Takte ab Abschnittsstart.', 'daw', '["importiert", "Beat-/Taktgenaues Schneiden"]', 37, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Beat-/Taktgenaues Schneiden", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Taktbereich verschieben';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Taktbereich verschieben', 'Verschiebe den angegebenen Taktbereich an eine neue Position.

Nutze BeatNet+-Downbeats als verbindliche Referenz. Bestimme den Quellbereich über vollständige Takte und schneide ihn taktgenau heraus oder kopiere ihn, je nach gewünschter Bearbeitung. Füge den Bereich an der Zielposition auf einer passenden Downbeat-/Taktgrenze ein.

Achte darauf, dass alle nachfolgenden Clips zeitlich korrekt verschoben werden und keine Lücken oder Überlappungen entstehen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Verschiebt einen bestimmten Taktbereich an eine neue Position.', 'daw', '["importiert", "Beat-/Taktgenaues Schneiden"]', 38, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Beat-/Taktgenaues Schneiden", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Loop sauber machen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Loop sauber machen', 'Korrigiere den Loop so, dass er sauber und taktgenau wiederholt.

Analysiere den aktuellen Loop-Bereich anhand von BeatNet+-Downbeats. Verschiebe Start und Ende auf vollständige Taktgrenzen, sodass der Loop beim Wiederholen ohne rhythmischen Versatz, Stolpern oder hörbaren Schnitt zurück auf den Anfang springt.

Nutze bei Bedarf minimale Fades, aber verändere den Klang nicht unnötig. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.', 'Korrigiert Start/Ende eines Loops auf perfekte Wiederholung.', 'daw', '["importiert", "Beat-/Taktgenaues Schneiden"]', 39, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Beat-/Taktgenaues Schneiden", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'SRT an Schnitt anpassen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('SRT an Schnitt anpassen', 'Passe die SRT-Zeitstempel an die aktuelle Audio-Bearbeitung an.

Analysiere die vorgenommenen Schnitte, Duplikationen oder Verschiebungen und übertrage diese Änderungen auf alle betroffenen SRT-Zeitstempel. Wenn ein Audioabschnitt dupliziert wurde, dupliziere auch die passenden SRT-Zeilen mit entsprechend verschobenen Zeiten.

Erhalte den Textinhalt unverändert, außer eine Korrektur ist ausdrücklich gewünscht. Speichere die angepasste SRT als neue Datei passend zur editierten Audio-Variante.', 'Verschiebt Untertitelzeiten passend zur Audio-Editierung.', 'daw', '["importiert", "Vocals / Lyrics / SRT"]', 40, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Vocals / Lyrics / SRT", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Hook-Zeilen finden';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Hook-Zeilen finden', 'Finde die Hook-Zeilen im Song.

Analysiere Lyrics und SRT auf wiederholte Zeilen, Refrain-Marker, Hook-Strukturen und wiederkehrende Phrasen. Bestimme daraus den wahrscheinlichsten Hook-Bereich inklusive Start, Ende und Taktanzahl anhand der BeatNet+-Downbeats.

Schneide noch nichts. Gib nur eine strukturierte Analyse aus, welche Zeilen zur Hook gehören und welche Zeit-/Taktbereiche dafür erkannt wurden.', 'Erkennt die Hook anhand wiederholter Lyrics-Zeilen.', 'daw', '["importiert", "Vocals / Lyrics / SRT"]', 41, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Vocals / Lyrics / SRT", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Doppelte Zeilen beachten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Doppelte Zeilen beachten', 'Berücksichtige doppelte oder abweichend wiederholte Zeilen bei der Schnittanalyse.

Vergleiche Lyrics, SRT und tatsächliche Songstruktur. Achte darauf, dass Zeilen im Audio doppelt vorkommen können, obwohl sie im geschriebenen Text nur einmal stehen, oder dass erwartete Wiederholungen im Audio fehlen können. Nutze BeatNet+-Downbeats und SRT-Zeiten, um die tatsächliche gesungene Struktur zu bestimmen.

Schneide nur anhand der realen Audio-/SRT-Struktur, nicht starr anhand des geschriebenen Songtexts. Arbeite non-destruktiv.', 'Berücksichtigt Suno-typische Wiederholungen beim Schnitt.', 'daw', '["importiert", "Vocals / Lyrics / SRT"]', 42, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Vocals / Lyrics / SRT", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Vocal-Einsatz finden';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Vocal-Einsatz finden', 'Finde den ersten relevanten Vocal-Einsatz im Song.

Analysiere SRT, Lyrics und Audio-Timing. Bestimme den ersten gesungenen oder gerappten Einsatz und snappe den Start auf die vorherige passende BeatNet+-Taktgrenze. Unterscheide dabei zwischen Intro-Adlibs, gesprochenem Vorlauf und dem eigentlichen ersten Part.

Schneide noch nichts. Gib Startzeit, Taktposition und kurze Begründung aus.', 'Findet den ersten gesungenen oder gerappten Einsatz.', 'daw', '["importiert", "Vocals / Lyrics / SRT"]', 43, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Vocals / Lyrics / SRT", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Adlibs erhalten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Adlibs erhalten', 'Erhalte wichtige Adlibs bei der Bearbeitung.

Analysiere SRT, Lyrics und BeatNet+-Taktgrenzen. Prüfe bei jedem geplanten Schnitt, ob direkt vor oder nach dem Schnitt wichtige Adlibs, Call-ins, Backing-Vocals oder Übergangsvocals liegen. Verschiebe den Schnittpunkt bei Bedarf auf eine musikalisch bessere Taktgrenze, damit diese Elemente nicht versehentlich abgeschnitten werden.

Arbeite ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Speichere die Bearbeitung non-destruktiv als neue Variante.', 'Achtet darauf, Adlibs nicht versehentlich abzuschneiden.', 'daw', '["importiert", "Vocals / Lyrics / SRT"]', 44, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Vocals / Lyrics / SRT", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Lyrics mit Audio abgleichen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Lyrics mit Audio abgleichen', 'Gleiche Lyrics und Audio-Struktur miteinander ab.

Vergleiche den geschriebenen Songtext mit SRT-Zeitstempeln, tatsächlichen Vocal-Einsätzen und BeatNet+-Downbeats. Erkenne Abweichungen wie ausgelassene Zeilen, doppelte Zeilen, verschobene Hooks, zusätzliche Adlibs oder andere Abschnittsreihenfolgen.

Schneide noch nichts. Erzeuge eine strukturierte Analyse mit erkannten Abweichungen und empfohlenen Schnittbereichen.', 'Vergleicht Lyrics/SRT mit tatsächlicher Songstruktur.', 'daw', '["importiert", "Vocals / Lyrics / SRT"]', 45, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Vocals / Lyrics / SRT", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Edit als Variante speichern';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Edit als Variante speichern', 'Speichere die aktuelle Bearbeitung als neue editierte Variante.

Überschreibe keine Originaldateien. Erzeuge eine neue Audio-Variante mit nachvollziehbarem Namen, speichere alle Schnittentscheidungen in einem Edit-Report und verknüpfe die neue Variante mit dem ursprünglichen Song oder Audio-Asset.

Erhalte vorhandene Metadaten, Pfade, SRT-Dateien und Projektstruktur so weit wie möglich. Arbeite non-destruktiv und auditierbar.', 'Speichert die Bearbeitung non-destruktiv als neue Version.', 'daw', '["importiert", "Export / Varianten"]', 46, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Export / Varianten", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Original behalten';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Original behalten', 'Bearbeite den Song non-destruktiv und behalte das Original unverändert.

Alle Schnitte, Duplikationen, Verschiebungen oder Exporte sollen als neue Variante gespeichert werden. Die Original-Audiodatei, ursprüngliche SRT-Dateien, Metadaten und Projektverweise dürfen nicht überschrieben oder gelöscht werden.

Erzeuge einen nachvollziehbaren Edit-Report mit allen Start-, End- und Insert-Zeitpunkten.', 'Führt alle Änderungen ohne Überschreiben der Originaldatei aus.', 'daw', '["importiert", "Export / Varianten"]', 47, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Export / Varianten", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Edit-Report erzeugen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Edit-Report erzeugen', 'Erzeuge einen vollständigen Edit-Report zur aktuellen Bearbeitung.

Dokumentiere Quellbereich, Zielposition, Startzeit, Endzeit, Insert-Zeit, Taktpositionen, verwendete BeatNet+-Downbeats, erkannte Songabschnitte, KI-Entscheidung, Confidence, Begründung und exportierte Dateien.

Der Report soll maschinenlesbar als JSON gespeichert werden und die Bearbeitung später nachvollziehbar oder wiederholbar machen.', 'Erstellt einen JSON-Bericht mit Schnittpunkten und Entscheidungen.', 'daw', '["importiert", "Export / Varianten"]', 48, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Export / Varianten", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'WAV-Version exportieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('WAV-Version exportieren', 'Exportiere die bearbeitete Version als WAV-Datei.

Nutze die aktuelle editierte Audio-Variante und exportiere sie verlustfrei oder möglichst qualitätsschonend als WAV. Überschreibe nicht das Original. Behalte Samplerate, Kanäle und Lautstärke so weit wie möglich bei.

Erzeuge zusätzlich einen Edit-Report und verknüpfe die WAV-Datei mit der neuen Variante.', 'Exportiert die bearbeitete Version verlustfrei als WAV.', 'daw', '["importiert", "Export / Varianten"]', 49, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Export / Varianten", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'MP3-Version exportieren';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('MP3-Version exportieren', 'Exportiere zusätzlich eine MP3-Version der bearbeiteten Variante.

Nutze die aktuelle editierte Audio-Variante als Quelle und erstelle daraus eine MP3-Datei mit hoher Qualität. Überschreibe nicht das Original. Die MP3 soll als zusätzliche Exportdatei zur gleichen Variante gespeichert werden.

Erzeuge oder aktualisiere den Edit-Report mit Pfad, Format, Bitrate und Dauer der exportierten Datei.', 'Exportiert zusätzlich eine komprimierte MP3-Version.', 'daw', '["importiert", "Export / Varianten"]', 50, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Export / Varianten", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Vorher/Nachher prüfen';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Vorher/Nachher prüfen', 'Prüfe die Bearbeitung im Vorher/Nachher-Vergleich.

Vergleiche Original und editierte Variante hinsichtlich Länge, Schnittpunkten, eingefügten Bereichen, Taktpositionen, SRT-Verschiebungen und Songstruktur. Prüfe, ob die Bearbeitung musikalisch logisch ist, keine unerwarteten Lücken oder Überlappungen entstanden sind und alle Übergänge taktgenau sitzen.

Gib eine kurze technische Zusammenfassung mit möglichen Warnungen aus.', 'Vergleicht Länge, Schnittpunkte und Songstruktur nach dem Edit.', 'daw', '["importiert", "Export / Varianten"]', 51, 1, '{"source_file": ".aufhaenger/daw_gespraechsaufhaenger_prompts.md", "source_category": "Export / Varianten", "imported_from_markdown": true, "imported_at": "2026-07-09T23:24:51", "imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
DELETE FROM daw_prompt_hooks WHERE scope = 'daw' AND title = 'Erste 8-Takte Hook';
INSERT INTO daw_prompt_hooks (title, prompt, description, scope, tags_json, sort_order, is_active, metadata_json, is_deleted, deleted_at, deleted_reason) VALUES ('Erste 8-Takte Hook', 'Verdopple die erste Hook. Nutze dafür ausschließlich die ersten 8 vollständigen Takte der ersten Hook. Erkenne den Start der ersten Hook anhand der Lyrics-/SRT-Struktur und der BeatNet+-Downbeats. Schneide ab dem ersten vollständigen Hook-Takt exakt 8 Takte lang. Kopiere diese 8 Takte und füge sie direkt danach erneut ein. Falls nach der Hook ein Übergangsauftakt in den nächsten Verse folgt, darf dieser nicht mitkopiert werden. Der Ablauf soll danach sein: erste 8 Hook-Takte, kopierte 8 Hook-Takte, danach der bestehende weitere Songverlauf.', 'Erste 8-Takte Hook', 'daw', '[]', 100, 1, '{"imported_from_export": true, "exported_at": "2026-07-09T23:27:12+00:00"}', 0, NULL, NULL);
COMMIT;
