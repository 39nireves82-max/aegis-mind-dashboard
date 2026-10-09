# 🏛️ INVARIX — MODUL RESONO: ARCHITEKTUR- UND ENTSCHEIDUNGS-FREEZE (v0.2.0)
Stand: 05. Oktober 2026 | Branch: feature/resono | Status: Mathematischer Freeze

---

## 1. Das Kernproblem & Die Daseinsberechtigung von RESONO
- Warum ein reines Signal nicht ausreicht: Ein Signal (AEGIS MIND) bewertet nur den Markt, nicht das Konto.
- Die Prop-Falle: Gleiche Positionsgrößen auf heterogenen Konten (frische Evaluation vs. angekratztes PA-Konto) führen unweigerlich zur Zerstörung von Konten mit geringem Puffer.
- Die Rolle von RESONO: Unbestechlicher Cluster-Risikofilter und Schiedsrichter zwischen Signalgenerierung und Order-Routing. Keine direkte Broker-Anbindung (Aufgabe von EXECUTOR), sondern reine Schutzlogik.

---

## 2. Die Puffer-Mathematik & Die Apex-Realität (Warum 50.100 $ und 2.500 $ Puffer?)
- Das Apex Trailing High-Watermark Modell: Verluste werden unerbittlich gegen offene Buchgewinne gerechnet, bis der Trailing Stop bei 50.100 USD (bzw. 100 USD über Start) einfriert.
- Warum der 50.100 USD Freeze-Punkt entscheidend ist: Erst ab diesem Punkt verwandelt sich das Fremdkapitalkonto in ein echtes Sicherheitsdepot, bei dem Gewinne permanenten Risikopuffer aufbauen und nicht mehr vom Trailing Stop aufgefressen werden.
- Die 3 Puffer-Zonen (Begründung der Schwellen):
  * Grüne Zone (>= 1.500 USD): Mindestens 60% des Ursprungspuffers vorhanden. Volle Handlungsfähigkeit.
  * Gelbe Zone (800 bis 1.499 USD): Akute Warnzone. Ein schlechter Tag mit 2 Fehltrades darf das Konto nicht killen. Zwingende Drosselung auf maximal 1 Micro.
  * Rote Zone (< 800 USD): Koma-Patient. Jede normale Volatilität führt zum Account-Verlust.

---

## 3. Die Asymmetrie der Assets (Warum MCL gesperrt und NQ als Sniper?)
- Warum Rohöl (MCL) in der Roten Zone verboten ist:
  * MCL besitzt mit 100 USD/Punkt und einer durchschnittlichen Kerzenspanne (ATR) von 0.40–0.80 USD ein unberechenbares Whipsaw-Risiko (40–80 USD pro Fehltrade). Bei einem Restpuffer unter 800 USD reichen 2 Fehltrades für eine Kontoverletzung.
- Warum NQ im Sniper-Modus rehabilitieren darf:
  * NQ (MNQ) tickt mit 2.00 USD/Punkt. Bei hochqualitativen A+-Setups lassen sich Stops von 15 Punkten (30 USD Risiko) realisieren.
  * Die 20%-Schranke: Das monetäre Trade-Risiko darf niemals 20% des verbleibenden Restpuffers übersteigen (z. B. max. 60 USD Risiko bei 300 USD Puffer). Das gibt einem stummen Konto rechnerisch mindestens 5 Chancen auf eine statistische Trendwende, statt mit der Brechstange liquidiert zu werden.

---

## 4. Phasen-Resonanz (Evaluation vs. Funded PA)
- Die Challenge-Divergenz:
  * Evaluation: Zeit- und Ziel-Flaschenhals (3.000 USD Profit Target). Mit 1 Micro dauert das Überwinden der Hürde bei 1–2 Signalen/Woche bis zu 6 Monate. Daher: Kontrollierte Skalierung auf bis zu 3 MNQ / 2 MCL in der Grünen Zone (Target erreichbar in 8–10 Treffern).
  * Funded / PA: Kein Profit-Ziel mehr vorhanden, nur noch Kapitalschutz und Auszahlungs-Konsistenz. Daher: Strikt konservativer Festungsmodus (1–2 Micros), bis die 50.100 USD Schwelle weit hinter sich gelassen wurde (ab 53.100 USD Kontostand).

---

## 5. Das Kollisions-Veto & Die Plateau-Distanz (Warum Qualität vor Score geht?)
- Maximal 1 Trade pro Prop-Konto: Parallele Positionen multiplizieren das Drawdown-Risiko unkontrolliert.
- Das Problem der Signal-Gleichzeitigkeit: Rohöl (Pit-Session 14:30–17:30 MEZ) und Nasdaq (US-RTH 15:30–21:30 MEZ) überschneiden sich am Nachmittag.
- Warum nicht der höchste Master-Score gewinnt, sondern die Plateau-Distanz:
  * Ein Score von 90 ist oft eine überhitzte Überdehnung (Flummi-Effekt).
  * Validierte Parameter-Plateaus: NQ performt empirisch optimal bei Score 55–60; MCL optimal bei Score 65–70.
  * Die Engine belohnt die Nähe zum statistischen Sweetspot, nicht numerischen Maximalismus.

---

## 6. Die FTMO-Forex Trennung (Warum zwei getrennte Berechnungs-Welten?)
- Balance-basiert statt High-Watermark: FTMO rechnet nicht gegen Intraday-Peaks, sondern starr gegen das Tages-Startkapital (5% Tagesverlust) und Initial-Kapital (10% Max Drawdown).
- Lot-Mathematik statt Punkterisiko: Forex erfordert Pip-Wert-Berechnung und Lot-Sizing auf 2 Dezimalstellen.
- Risikobudgetierung: 5.0% des verbleibenden Tagespuffers in Grün (entspricht validiertem Master-Kader), 2.5% in Gelb, 0.0% (Tages-Notbremse) in Rot unter 1.500 USD Puffer.