# SolParc

Aplicació web per a triar parc infantil a València segons el sol i l'ombra.
Calcula la posició del sol en temps real i mostra, per a 401 zones de jocs de la ciutat,
quina part està a l'ombra cada mitja hora (a partir dels arbres i edificis d'OpenStreetMap).

## Com obrir-la

És un sol fitxer: `index.html`. Es pot obrir directament al navegador o publicar amb GitHub Pages.

## Dades i valoracions

- Les fitxes que afegiu o editeu i les valoracions es guarden **només al navegador de cada dispositiu** (localStorage).
  La versió publicada a Claude les comparteix entre famílies; aquesta còpia de GitHub, no.
- El càlcul solar usa [SunCalc](https://github.com/mourner/suncalc) (llicència BSD-2).

## Com es van calcular les ombres

`eines/build_parks.py` llig tres exportacions d'Overpass Turbo (zones de jocs, arbres i edificis)
i calcula, per al dia 15 de cada mes i cada mitja hora, el percentatge de cada zona a l'ombra.
És una estimació: no compta tendals, pèrgoles ni arbres que no estiguen al mapa.

## Llicència de les dades

Dades del mapa © [col·laboradors d'OpenStreetMap](https://www.openstreetmap.org/copyright),
disponibles sota la llicència Open Database License (ODbL). Les dades de parcs i ombres incloses
a `index.html` són una base de dades derivada i es distribueixen sota la mateixa llicència ODbL.
