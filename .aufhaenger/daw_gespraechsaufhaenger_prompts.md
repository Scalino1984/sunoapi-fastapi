# DAW-Gesprächsaufhänger mit vollständigen Prompts

Sammlung wiederverwendbarer DAW-KI-Arbeitsschritte für taktgenaue Audio-Bearbeitung mit Lyrics-/SRT-Struktur, BeatNet-/Downbeat-Timings und non-destruktivem Export als neue editierte Variante.

---

## 1. Bereits definierte Hook-Prompts

### Hook + Übergang doppeln

**Minimale Beschreibung:** Verdoppelt die erste Hook inklusive nachfolgendem Übergangsauftakt zum nächsten Verse.

```text
Setze die erste Hook doppelt und berücksichtige dabei den Übergangsauftakt nach der Hook.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Taktgrenzen. Bestimme nicht nur den eigentlichen Hook-Bereich, sondern auch den direkt nachfolgenden musikalischen Übergangsauftakt zum nächsten Verse, falls dieser rhythmisch oder musikalisch noch zur Hook-Phrase gehört.

Kopiere den Bereich vom Hook-Start bis einschließlich des Übergangsauftakts nach der Hook und füge ihn direkt danach erneut ein. Der nächste Verse soll erst nach der zweiten Kopie des Übergangsauftakts beginnen.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Hook doppeln, Übergang behalten

**Minimale Beschreibung:** Verdoppelt nur die erste Hook und lässt den bestehenden Übergangsauftakt einmal vor dem nächsten Verse stehen.

```text
Setze die erste Hook doppelt, aber lasse den Übergangsauftakt zum nächsten Verse nur einmal stehen.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Taktgrenzen. Bestimme das Ende der eigentlichen Hook vor dem nachfolgenden Übergangsauftakt. Kopiere nur den reinen Hook-Bereich und füge ihn direkt vor dem bestehenden Übergangsauftakt ein.

Der Ablauf soll danach sein: erste Hook, kopierte Hook, bestehender Übergangsauftakt, nächster Verse.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Der Übergangsauftakt darf nicht mitkopiert werden, wenn er eindeutig in den nächsten Verse hineinführt. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Hook 4 Takte doppeln

**Minimale Beschreibung:** Verdoppelt ausschließlich die ersten 4 vollständigen Takte der ersten Hook.

```text
Verdopple die erste Hook. Nutze dafür ausschließlich die ersten 4 vollständigen Takte der ersten Hook.

Erkenne den Start der ersten Hook anhand der Lyrics-/SRT-Struktur und der BeatNet+-Downbeats. Schneide ab dem ersten vollständigen Hook-Takt exakt 4 Takte lang. Kopiere diese 4 Takte und füge sie direkt danach erneut ein.

Falls nach der Hook ein Übergangsauftakt in den nächsten Verse folgt, darf dieser nicht mitkopiert werden. Der Ablauf soll danach sein: erste 4 Hook-Takte, kopierte 4 Hook-Takte, danach der bestehende weitere Songverlauf.
```

---

## 2. Hook / Refrain

### Hook auf 8 Takte verlängern

**Minimale Beschreibung:** Verlängert eine 4-Takt-Hook durch Duplikation auf 8 Takte.

```text
Verlängere die erste Hook auf 8 Takte.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme den Start der Hook exakt auf der ersten vollständigen Hook-Taktgrenze. Nutze die ersten 4 vollständigen Hook-Takte als Quellbereich, kopiere sie und füge sie direkt danach erneut ein, sodass die Hook anschließend 8 vollständige Takte umfasst.

Falls nach der Hook ein Übergang oder Auftakt zum nächsten Verse folgt, lasse diesen Übergang nur einmal nach der verlängerten Hook stehen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Hook-Ende sauber setzen

**Minimale Beschreibung:** Schneidet das Hook-Ende exakt auf die nächste Taktgrenze.

```text
Setze das Ende der ersten Hook sauber auf eine musikalisch passende Taktgrenze.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme, wo der eigentliche Hook-Inhalt endet, und verschiebe das Hook-Ende auf die nächste saubere Downbeat- oder Bar-Grenze, ohne Wörter, Adlibs, Fills oder Übergänge unnatürlich abzuschneiden.

Der bestehende Songverlauf soll musikalisch flüssig bleiben. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Letzte Hook verlängern

**Minimale Beschreibung:** Macht den finalen Refrain länger und epischer.

```text
Verlängere die letzte Hook des Songs.

Erkenne die letzte Hook anhand der Lyrics-/SRT-Struktur, wiederholter Hook-Zeilen und BeatNet+-Taktgrenzen. Bestimme einen musikalisch vollständigen Hook-Bereich und dupliziere ihn direkt vor dem Outro oder Songende, sodass der finale Refrain länger und wirkungsvoller wird.

Achte darauf, vorhandene Outro-Übergänge, Schlussfills und Fade-Outs nicht unnötig zu beschädigen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Hook vorziehen

**Minimale Beschreibung:** Verschiebt die erste Hook früher in den Song.

```text
Ziehe die erste Hook im Arrangement früher nach vorne.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme einen passenden früheren Einfügepunkt auf einer vollständigen Taktgrenze, idealerweise nach einem sinnvollen Verse- oder Intro-Ende. Verschiebe oder kopiere die Hook so, dass sie früher im Song erscheint und der Ablauf musikalisch schlüssig bleibt.

Bestehende Übergänge sollen erhalten oder sauber angepasst werden. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Hook wiederholen

**Minimale Beschreibung:** Fügt die erste Hook später im Song erneut ein.

```text
Füge die erste Hook später im Song erneut ein.

Erkenne die erste vollständige Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kopiere den vollständigen Hook-Bereich taktgenau und füge ihn an einer musikalisch sinnvollen späteren Stelle erneut ein, zum Beispiel nach Verse 2 oder vor dem Outro.

Achte darauf, Übergänge, Auftakte und vorhandene Songstruktur sauber zu erhalten. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Hook ohne Übergang doppeln

**Minimale Beschreibung:** Verdoppelt die Hook ohne Intro-, Fill- oder Verse-Übergang.

```text
Verdopple die erste Hook ohne nachfolgenden Übergang.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme nur den reinen Hook-Bereich vom ersten vollständigen Hook-Takt bis zum Ende der letzten vollständigen Hook-Phrase. Kopiere keine nachfolgenden Drumfills, Turnarounds, Adlibs oder Auftakte zum nächsten Verse mit.

Füge die kopierte Hook direkt nach dem reinen Hook-Bereich ein. Der bestehende Übergang zum nächsten Abschnitt soll danach nur einmal stehen bleiben. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

## 3. Verse / Parts

### Verse doppeln

**Minimale Beschreibung:** Dupliziert den ersten vollständigen Verse taktgenau.

```text
Verdopple den ersten vollständigen Verse.

Erkenne den ersten Verse anhand der Lyrics-/SRT-Struktur, Vocal-Einsätze und BeatNet+-Downbeats. Bestimme den vollständigen Verse-Bereich von der ersten Verse-Taktgrenze bis zur letzten vollständigen Verse-Taktgrenze vor Hook, Bridge oder Übergang. Kopiere diesen Bereich und füge ihn direkt danach erneut ein.

Achte darauf, dass Übergänge zur Hook nicht doppelt oder unnatürlich abgeschnitten werden. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Verse kürzen

**Minimale Beschreibung:** Entfernt ausgewählte Takte aus einem Verse.

```text
Kürze den ersten Verse taktgenau.

Erkenne den ersten Verse anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Entferne musikalisch sinnvolle vollständige Takte aus dem Verse, ohne Wörter, Reimphrasen oder Übergänge unnatürlich abzuschneiden. Bevorzuge Bereiche mit Wiederholungen, Pausen oder weniger wichtigen Zeilen.

Verbinde den verbleibenden Verse sauber mit dem nachfolgenden Abschnitt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Verse austauschen

**Minimale Beschreibung:** Ersetzt einen Verse-Bereich durch einen anderen Songabschnitt.

```text
Tausche einen Verse-Bereich gegen einen anderen passenden Songabschnitt aus.

Erkenne den Ziel-Verse anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme einen gleich langen oder musikalisch kompatiblen Ersatzbereich aus dem Song. Entferne den Zielbereich und setze den Ersatzbereich an dessen Position ein.

Achte auf Taktlänge, Downbeats, Übergänge, Vocal-Einsätze und saubere Anschlussstellen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Verse 2 früher starten

**Minimale Beschreibung:** Entfernt Zwischenraum vor Verse 2 und setzt ihn früher.

```text
Lasse Verse 2 früher starten.

Erkenne den Start von Verse 2 anhand der Lyrics-/SRT-Struktur, Vocal-Einsätze und BeatNet+-Downbeats. Bestimme den Bereich direkt vor Verse 2, der entfernt oder gekürzt werden kann, zum Beispiel überlange Pausen, Wiederholungen, Fills oder unnötige Zwischenparts.

Entferne diesen Bereich taktgenau, sodass Verse 2 früher startet und musikalisch sauber an den vorherigen Abschnitt anschließt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### 16 Takte extrahieren

**Minimale Beschreibung:** Schneidet exakt 16 Takte ab gewähltem Abschnitt heraus.

```text
Extrahiere exakt 16 vollständige Takte aus dem gewünschten Abschnitt.

Erkenne den Start des relevanten Abschnitts anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Schneide ab der ersten passenden vollständigen Taktgrenze exakt 16 Takte heraus. Der extrahierte Bereich soll als eigener Clip oder neue Variante gespeichert werden.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Vermeide abgeschnittene Wörter, unvollständige Vocal-Phrasen und halbe Übergänge. Arbeite non-destruktiv.
```

---

### Part loopen

**Minimale Beschreibung:** Loopt einen Verse-, Hook- oder Instrumentalabschnitt sauber auf Bar-Grenzen.

```text
Erstelle einen sauberen Loop aus dem gewählten Part.

Erkenne den gewünschten Part anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Bestimme Start und Ende so, dass der Bereich auf vollständigen Taktgrenzen liegt und beim Wiederholen rhythmisch sauber zurück auf den Anfang springt. Kopiere den Bereich und wiederhole ihn in der gewünschten Länge.

Achte auf Downbeat-Konsistenz, saubere Loop-Enden und natürliche Übergänge. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

## 4. Intro / Outro

### Intro kürzen

**Minimale Beschreibung:** Entfernt überflüssige Intro-Takte vor dem ersten Einsatz.

```text
Kürze das Intro des Songs.

Erkenne das Intro anhand der Lyrics-/SRT-Struktur, des ersten Vocal-Einsatzes und BeatNet+-Downbeats. Entferne überflüssige vollständige Intro-Takte vor dem ersten wichtigen Einsatz, ohne den musikalischen Einstieg unnatürlich abzuschneiden.

Der Song soll danach schneller und direkter starten. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Intro verlängern

**Minimale Beschreibung:** Dupliziert Intro-Takte für längeren Einstieg.

```text
Verlängere das Intro des Songs.

Erkenne das Intro anhand der Lyrics-/SRT-Struktur, BeatNet+-Downbeats und des ersten Vocal-Einsatzes. Wähle einen musikalisch sauberen Intro-Bereich von vollständigen Takten, kopiere ihn und füge ihn vor dem ersten Einsatz erneut ein, sodass der Einstieg länger wirkt.

Achte darauf, dass der erste Vocal-Einsatz weiterhin sauber auf einer passenden Taktgrenze beginnt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Direkt zur Hook starten

**Minimale Beschreibung:** Entfernt Intro/Verse-Anfang und startet beim ersten Refrain.

```text
Erstelle eine Version, die direkt mit der ersten Hook startet.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Entferne alle vorherigen Bereiche bis zum Start der ersten vollständigen Hook oder bis zu einem musikalisch passenden Auftakt unmittelbar vor der Hook.

Der neue Songstart soll sauber, druckvoll und nicht abgeschnitten wirken. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Outro verlängern

**Minimale Beschreibung:** Wiederholt die letzten Takte für ein längeres Outro.

```text
Verlängere das Outro des Songs.

Erkenne das Outro oder die letzten musikalisch vollständigen Takte anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kopiere einen passenden Schlussbereich und füge ihn vor dem endgültigen Ende erneut ein, sodass das Outro länger wirkt.

Achte darauf, dass ein vorhandener Schlussakzent oder Fade-Out nicht unnatürlich doppelt erscheint. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Fade-Out setzen

**Minimale Beschreibung:** Erstellt ein sauberes Fade-Out am Songende.

```text
Setze ein sauberes Fade-Out am Songende.

Erkenne das musikalische Ende anhand der letzten vollständigen Taktgrenzen und BeatNet+-Downbeats. Lege den Fade-Out so an, dass er musikalisch natürlich beginnt und auf dem Songende sauber ausläuft. Schneide bei Bedarf das Ende auf die nächste passende Taktgrenze.

Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Outro abschneiden

**Minimale Beschreibung:** Schneidet den Song nach der letzten vollständigen Taktgrenze ab.

```text
Schneide das Outro nach der letzten sinnvollen vollständigen Taktgrenze ab.

Erkenne das Ende des musikalisch relevanten Songs anhand der Lyrics-/SRT-Struktur, BeatNet+-Downbeats und des letzten klaren musikalischen Abschlusses. Entferne überlange Ausläufe, Pausen oder unnötige Wiederholungen nach diesem Punkt.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Setze bei Bedarf ein kurzes sauberes Fade-Out. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

## 5. Übergänge / Fills / Auftakte

### Übergang behalten

**Minimale Beschreibung:** Lässt einen bestehenden Übergang nur einmal vor dem nächsten Part stehen.

```text
Behalte den bestehenden Übergang zum nächsten Part nur einmal.

Erkenne den zu bearbeitenden Abschnitt und den nachfolgenden Übergang anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Wenn der Abschnitt dupliziert oder verlängert wird, kopiere den Übergang nicht mit. Der bestehende Übergang soll nach der Kopie weiterhin genau einmal direkt vor dem nächsten Part stehen.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Übergang doppeln

**Minimale Beschreibung:** Kopiert Hook plus nachfolgenden Übergangsauftakt gemeinsam.

```text
Dopple den Abschnitt inklusive nachfolgendem Übergang.

Erkenne den gewünschten Abschnitt und den direkt folgenden musikalischen Übergang anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Wenn der Übergang rhythmisch oder musikalisch noch zur Phrase gehört, kopiere den Abschnitt inklusive dieses Übergangs und füge ihn direkt danach erneut ein.

Der nächste Songabschnitt soll erst nach der zweiten Kopie des Übergangs beginnen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Fill isolieren

**Minimale Beschreibung:** Schneidet einen Drumfill oder Turnaround als eigenen Bereich heraus.

```text
Isoliere den markanten Fill oder Turnaround als eigenen Bereich.

Erkenne den Fill anhand von BeatNet+-Downbeats, auffälligen rhythmischen Änderungen und der Position zwischen zwei Songabschnitten. Schneide den Fill von der vorherigen passenden Taktgrenze bis zur nachfolgenden passenden Taktgrenze als eigenen Clip heraus.

Der Fill soll später wieder sauber vor Hooks, Verses oder Breaks eingefügt werden können. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv.
```

---

### Fill vor Hook setzen

**Minimale Beschreibung:** Fügt einen vorhandenen Übergangsfill direkt vor die Hook.

```text
Setze einen vorhandenen Fill direkt vor die erste Hook.

Erkenne die erste Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Suche einen passenden vorhandenen Drumfill oder Turnaround im Song, kopiere ihn taktgenau und füge ihn unmittelbar vor dem Hook-Start ein.

Achte darauf, dass der Hook-Start weiterhin sauber auf dem Downbeat liegt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Auftakt erkennen

**Minimale Beschreibung:** Findet musikalische Lead-ins vor oder nach einem Abschnitt.

```text
Erkenne den musikalischen Auftakt eines Abschnitts.

Analysiere Lyrics-/SRT-Struktur, BeatNet+-Downbeats, Vocal-Einsätze, Drumfills, Adlibs und musikalische Lead-ins. Bestimme, ob der Auftakt vor dem Abschnitt liegt, nach dem Abschnitt in den nächsten Part führt oder als eigenständiger Übergang behandelt werden sollte.

Gib Start und Ende des Auftakts taktgenau an und beschreibe, ob er beim Duplizieren mitkopiert oder nur einmal stehen bleiben soll. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen.
```

---

### Übergang glätten

**Minimale Beschreibung:** Verschiebt Schnittpunkte auf passende Beat-/Taktgrenzen.

```text
Glätte den Übergang zwischen zwei geschnittenen Songabschnitten.

Analysiere die Schnittstelle anhand von BeatNet+-Downbeats, Taktgrenzen, Vocal-Phrasen und vorhandenen Fills. Verschiebe Start- und Endpunkte so, dass der Übergang rhythmisch stabil, musikalisch sauber und ohne hörbare Stolperstelle funktioniert.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Nutze bei Bedarf minimale Fades, aber vermeide unnötige Klangveränderungen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

## 6. Arrangement / Struktur

### Songstruktur analysieren

**Minimale Beschreibung:** Erkennt Intro, Verse, Hook, Bridge und Outro anhand von Lyrics/SRT/Beats.

```text
Analysiere die vollständige Songstruktur.

Erkenne anhand von Lyrics-/SRT-Struktur, wiederholten Textzeilen, Vocal-Einsätzen und BeatNet+-Downbeats die wichtigsten Abschnitte des Songs: Intro, Verse, Hook, Bridge, Break, Outro und Übergänge. Gib für jeden Abschnitt Start, Ende, geschätzte Taktanzahl und kurze Begründung aus.

Schneide noch nichts. Erzeuge nur eine strukturierte Analyse, die als Grundlage für spätere non-destruktive Bearbeitung verwendet werden kann.
```

---

### Arrangement verdichten

**Minimale Beschreibung:** Entfernt lange Pausen, Wiederholungen oder unnötige Zwischenparts.

```text
Verdichte das Arrangement des Songs.

Analysiere die Songstruktur anhand von Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Suche überlange Pausen, unnötige Wiederholungen, zu lange Intros, zu lange Outros oder Zwischenparts ohne klare Funktion. Entferne oder kürze nur vollständige musikalische Takte, damit der Song direkter und kompakter wirkt.

Achte darauf, Hooks, wichtige Verse-Zeilen, Übergänge und musikalische Höhepunkte zu erhalten. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Radioversion erstellen

**Minimale Beschreibung:** Kürzt den Song auf eine kompaktere Version.

```text
Erstelle eine kompakte Radioversion des Songs.

Analysiere Intro, Verse, Hook, Bridge, Outro und Wiederholungen anhand von Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kürze den Song auf eine straffere Version, indem du überlange Intros, doppelte Hooks, unnötige Bridges oder zu lange Outros reduzierst.

Die wichtigsten Songteile sollen erhalten bleiben. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Extended Version erstellen

**Minimale Beschreibung:** Verlängert Hook-, Intro- oder Outro-Bereiche.

```text
Erstelle eine Extended Version des Songs.

Analysiere die Songstruktur anhand von Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Verlängere musikalisch sinnvolle Bereiche wie Intro, Hook, Break oder Outro durch taktgenaue Duplikation. Die neue Version soll länger wirken, ohne künstlich oder unruhig zu klingen.

Achte auf saubere Übergänge, Downbeats und vollständige Phrasen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Bridge entfernen

**Minimale Beschreibung:** Entfernt einen Mittelteil und verbindet Hook/Verse sauber.

```text
Entferne die Bridge aus dem Song.

Erkenne die Bridge anhand der Lyrics-/SRT-Struktur, musikalischer Änderung und BeatNet+-Downbeats. Entferne den vollständigen Bridge-Bereich taktgenau und verbinde den vorherigen Abschnitt sauber mit dem nachfolgenden Abschnitt.

Achte darauf, dass der Übergang rhythmisch und musikalisch schlüssig bleibt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Neue Hook nach Verse 2

**Minimale Beschreibung:** Fügt eine vorhandene Hook nach dem zweiten Verse ein.

```text
Füge nach Verse 2 eine zusätzliche Hook ein.

Erkenne Verse 2 und die erste vollständige Hook anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Kopiere die Hook taktgenau und füge sie direkt nach Verse 2 oder nach dem dortigen Übergang ein, je nachdem was musikalisch sauberer ist.

Achte darauf, dass der neue Hook-Einsatz auf einer vollständigen Downbeat-/Taktgrenze beginnt. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

## 7. Beat-/Taktgenaues Schneiden

### Auf Takt schneiden

**Minimale Beschreibung:** Schneidet einen Bereich exakt auf Downbeat-/Bar-Grenzen.

```text
Schneide den gewünschten Bereich exakt auf Taktgrenzen.

Nutze BeatNet+-Downbeats als verbindliche rhythmische Referenz. Verschiebe Start und Ende des gewählten Bereichs auf die nächstliegenden musikalisch sinnvollen Downbeat- oder Bar-Grenzen. Vermeide Schnitte mitten in Wörtern, Vocal-Phrasen, Fills oder wichtigen Transienten.

Arbeite ausschließlich beat-, downbeat- und taktgenau. Speichere das Ergebnis non-destruktiv als neue editierte Variante.
```

---

### 4 Takte kopieren

**Minimale Beschreibung:** Kopiert exakt 4 vollständige Takte ab Abschnittsstart.

```text
Kopiere exakt 4 vollständige Takte ab dem gewählten Abschnittsstart.

Erkenne den Abschnittsstart anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Setze den Start auf die erste passende vollständige Taktgrenze und kopiere exakt 4 vollständige Takte. Füge den kopierten Bereich direkt nach dem Originalbereich oder an der gewünschten Zielposition ein.

Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### 8 Takte kopieren

**Minimale Beschreibung:** Kopiert exakt 8 vollständige Takte ab Abschnittsstart.

```text
Kopiere exakt 8 vollständige Takte ab dem gewählten Abschnittsstart.

Erkenne den Abschnittsstart anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Setze den Start auf die erste passende vollständige Taktgrenze und kopiere exakt 8 vollständige Takte. Füge den kopierten Bereich direkt nach dem Originalbereich oder an der gewünschten Zielposition ein.

Achte darauf, keine Übergänge mitzunehmen, sofern sie nicht ausdrücklich Teil des Bereichs sein sollen. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### 16 Takte kopieren

**Minimale Beschreibung:** Kopiert exakt 16 vollständige Takte ab Abschnittsstart.

```text
Kopiere exakt 16 vollständige Takte ab dem gewählten Abschnittsstart.

Erkenne den Abschnittsstart anhand der Lyrics-/SRT-Struktur und BeatNet+-Downbeats. Setze den Start auf die erste passende vollständige Taktgrenze und kopiere exakt 16 vollständige Takte. Füge den kopierten Bereich direkt nach dem Originalbereich oder an der gewünschten Zielposition ein.

Der Bereich soll als vollständiger musikalischer Part funktionieren. Schneide ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Taktbereich verschieben

**Minimale Beschreibung:** Verschiebt einen bestimmten Taktbereich an eine neue Position.

```text
Verschiebe den angegebenen Taktbereich an eine neue Position.

Nutze BeatNet+-Downbeats als verbindliche Referenz. Bestimme den Quellbereich über vollständige Takte und schneide ihn taktgenau heraus oder kopiere ihn, je nach gewünschter Bearbeitung. Füge den Bereich an der Zielposition auf einer passenden Downbeat-/Taktgrenze ein.

Achte darauf, dass alle nachfolgenden Clips zeitlich korrekt verschoben werden und keine Lücken oder Überlappungen entstehen. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

### Loop sauber machen

**Minimale Beschreibung:** Korrigiert Start/Ende eines Loops auf perfekte Wiederholung.

```text
Korrigiere den Loop so, dass er sauber und taktgenau wiederholt.

Analysiere den aktuellen Loop-Bereich anhand von BeatNet+-Downbeats. Verschiebe Start und Ende auf vollständige Taktgrenzen, sodass der Loop beim Wiederholen ohne rhythmischen Versatz, Stolpern oder hörbaren Schnitt zurück auf den Anfang springt.

Nutze bei Bedarf minimale Fades, aber verändere den Klang nicht unnötig. Arbeite non-destruktiv und speichere das Ergebnis als neue editierte Variante.
```

---

## 8. Vocals / Lyrics / SRT

### SRT an Schnitt anpassen

**Minimale Beschreibung:** Verschiebt Untertitelzeiten passend zur Audio-Editierung.

```text
Passe die SRT-Zeitstempel an die aktuelle Audio-Bearbeitung an.

Analysiere die vorgenommenen Schnitte, Duplikationen oder Verschiebungen und übertrage diese Änderungen auf alle betroffenen SRT-Zeitstempel. Wenn ein Audioabschnitt dupliziert wurde, dupliziere auch die passenden SRT-Zeilen mit entsprechend verschobenen Zeiten.

Erhalte den Textinhalt unverändert, außer eine Korrektur ist ausdrücklich gewünscht. Speichere die angepasste SRT als neue Datei passend zur editierten Audio-Variante.
```

---

### Hook-Zeilen finden

**Minimale Beschreibung:** Erkennt die Hook anhand wiederholter Lyrics-Zeilen.

```text
Finde die Hook-Zeilen im Song.

Analysiere Lyrics und SRT auf wiederholte Zeilen, Refrain-Marker, Hook-Strukturen und wiederkehrende Phrasen. Bestimme daraus den wahrscheinlichsten Hook-Bereich inklusive Start, Ende und Taktanzahl anhand der BeatNet+-Downbeats.

Schneide noch nichts. Gib nur eine strukturierte Analyse aus, welche Zeilen zur Hook gehören und welche Zeit-/Taktbereiche dafür erkannt wurden.
```

---

### Doppelte Zeilen beachten

**Minimale Beschreibung:** Berücksichtigt Suno-typische Wiederholungen beim Schnitt.

```text
Berücksichtige doppelte oder abweichend wiederholte Zeilen bei der Schnittanalyse.

Vergleiche Lyrics, SRT und tatsächliche Songstruktur. Achte darauf, dass Zeilen im Audio doppelt vorkommen können, obwohl sie im geschriebenen Text nur einmal stehen, oder dass erwartete Wiederholungen im Audio fehlen können. Nutze BeatNet+-Downbeats und SRT-Zeiten, um die tatsächliche gesungene Struktur zu bestimmen.

Schneide nur anhand der realen Audio-/SRT-Struktur, nicht starr anhand des geschriebenen Songtexts. Arbeite non-destruktiv.
```

---

### Vocal-Einsatz finden

**Minimale Beschreibung:** Findet den ersten gesungenen oder gerappten Einsatz.

```text
Finde den ersten relevanten Vocal-Einsatz im Song.

Analysiere SRT, Lyrics und Audio-Timing. Bestimme den ersten gesungenen oder gerappten Einsatz und snappe den Start auf die vorherige passende BeatNet+-Taktgrenze. Unterscheide dabei zwischen Intro-Adlibs, gesprochenem Vorlauf und dem eigentlichen ersten Part.

Schneide noch nichts. Gib Startzeit, Taktposition und kurze Begründung aus.
```

---

### Adlibs erhalten

**Minimale Beschreibung:** Achtet darauf, Adlibs nicht versehentlich abzuschneiden.

```text
Erhalte wichtige Adlibs bei der Bearbeitung.

Analysiere SRT, Lyrics und BeatNet+-Taktgrenzen. Prüfe bei jedem geplanten Schnitt, ob direkt vor oder nach dem Schnitt wichtige Adlibs, Call-ins, Backing-Vocals oder Übergangsvocals liegen. Verschiebe den Schnittpunkt bei Bedarf auf eine musikalisch bessere Taktgrenze, damit diese Elemente nicht versehentlich abgeschnitten werden.

Arbeite ausschließlich auf Beat-, Downbeat- oder Taktgrenzen. Speichere die Bearbeitung non-destruktiv als neue Variante.
```

---

### Lyrics mit Audio abgleichen

**Minimale Beschreibung:** Vergleicht Lyrics/SRT mit tatsächlicher Songstruktur.

```text
Gleiche Lyrics und Audio-Struktur miteinander ab.

Vergleiche den geschriebenen Songtext mit SRT-Zeitstempeln, tatsächlichen Vocal-Einsätzen und BeatNet+-Downbeats. Erkenne Abweichungen wie ausgelassene Zeilen, doppelte Zeilen, verschobene Hooks, zusätzliche Adlibs oder andere Abschnittsreihenfolgen.

Schneide noch nichts. Erzeuge eine strukturierte Analyse mit erkannten Abweichungen und empfohlenen Schnittbereichen.
```

---

## 9. Export / Varianten

### Edit als Variante speichern

**Minimale Beschreibung:** Speichert die Bearbeitung non-destruktiv als neue Version.

```text
Speichere die aktuelle Bearbeitung als neue editierte Variante.

Überschreibe keine Originaldateien. Erzeuge eine neue Audio-Variante mit nachvollziehbarem Namen, speichere alle Schnittentscheidungen in einem Edit-Report und verknüpfe die neue Variante mit dem ursprünglichen Song oder Audio-Asset.

Erhalte vorhandene Metadaten, Pfade, SRT-Dateien und Projektstruktur so weit wie möglich. Arbeite non-destruktiv und auditierbar.
```

---

### Original behalten

**Minimale Beschreibung:** Führt alle Änderungen ohne Überschreiben der Originaldatei aus.

```text
Bearbeite den Song non-destruktiv und behalte das Original unverändert.

Alle Schnitte, Duplikationen, Verschiebungen oder Exporte sollen als neue Variante gespeichert werden. Die Original-Audiodatei, ursprüngliche SRT-Dateien, Metadaten und Projektverweise dürfen nicht überschrieben oder gelöscht werden.

Erzeuge einen nachvollziehbaren Edit-Report mit allen Start-, End- und Insert-Zeitpunkten.
```

---

### Edit-Report erzeugen

**Minimale Beschreibung:** Erstellt einen JSON-Bericht mit Schnittpunkten und Entscheidungen.

```text
Erzeuge einen vollständigen Edit-Report zur aktuellen Bearbeitung.

Dokumentiere Quellbereich, Zielposition, Startzeit, Endzeit, Insert-Zeit, Taktpositionen, verwendete BeatNet+-Downbeats, erkannte Songabschnitte, KI-Entscheidung, Confidence, Begründung und exportierte Dateien.

Der Report soll maschinenlesbar als JSON gespeichert werden und die Bearbeitung später nachvollziehbar oder wiederholbar machen.
```

---

### WAV-Version exportieren

**Minimale Beschreibung:** Exportiert die bearbeitete Version verlustfrei als WAV.

```text
Exportiere die bearbeitete Version als WAV-Datei.

Nutze die aktuelle editierte Audio-Variante und exportiere sie verlustfrei oder möglichst qualitätsschonend als WAV. Überschreibe nicht das Original. Behalte Samplerate, Kanäle und Lautstärke so weit wie möglich bei.

Erzeuge zusätzlich einen Edit-Report und verknüpfe die WAV-Datei mit der neuen Variante.
```

---

### MP3-Version exportieren

**Minimale Beschreibung:** Exportiert zusätzlich eine komprimierte MP3-Version.

```text
Exportiere zusätzlich eine MP3-Version der bearbeiteten Variante.

Nutze die aktuelle editierte Audio-Variante als Quelle und erstelle daraus eine MP3-Datei mit hoher Qualität. Überschreibe nicht das Original. Die MP3 soll als zusätzliche Exportdatei zur gleichen Variante gespeichert werden.

Erzeuge oder aktualisiere den Edit-Report mit Pfad, Format, Bitrate und Dauer der exportierten Datei.
```

---

### Vorher/Nachher prüfen

**Minimale Beschreibung:** Vergleicht Länge, Schnittpunkte und Songstruktur nach dem Edit.

```text
Prüfe die Bearbeitung im Vorher/Nachher-Vergleich.

Vergleiche Original und editierte Variante hinsichtlich Länge, Schnittpunkten, eingefügten Bereichen, Taktpositionen, SRT-Verschiebungen und Songstruktur. Prüfe, ob die Bearbeitung musikalisch logisch ist, keine unerwarteten Lücken oder Überlappungen entstanden sind und alle Übergänge taktgenau sitzen.

Gib eine kurze technische Zusammenfassung mit möglichen Warnungen aus.
```

---

## 10. Kompakte Favoritenliste

| Titel | Zweck |
|---|---|
| Hook 4 Takte doppeln | Exakt die ersten 4 Hook-Takte duplizieren |
| Hook auf 8 Takte verlängern | Kurze Hook auf 8 Takte erweitern |
| Übergang behalten | Übergang zum nächsten Part nur einmal stehen lassen |
| Intro kürzen | Überflüssigen Vorlauf entfernen |
| 16 Takte extrahieren | Vollständigen Rap-Part oder Abschnitt isolieren |
| Bridge entfernen | Mittelteil entfernen und sauber verbinden |
| Letzte Hook verlängern | Finalen Refrain größer machen |
| Loop sauber machen | Loopgrenzen auf Takt korrigieren |
| SRT an Schnitt anpassen | Untertitel nach Audio-Edit synchronisieren |
| Edit als Variante speichern | Non-destruktive neue Version erzeugen |
