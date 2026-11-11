# Map data notes

`countries50.json` is Natural Earth 1:50m admin-0 (public domain), reduced to name, ISO-3 code and outer rings.

One change from the Natural Earth default file: **Crimea is drawn as part of Ukraine**, following
internationally recognized borders (UN General Assembly resolution 68/262, and US policy). Natural Earth's
default file draws Crimea inside Russia, while it already draws the other areas Russia occupies inside
Ukraine; the change makes the map consistent. Done on 11 Nov 2026 by joining the Crimea polygon to
mainland Ukraine (shapely union), so no border line is drawn at the Perekop isthmus.

When a story involves a disputed area, label places neutrally and say "approximate" for anything you
place by hand. Do not tint countries on opposite sides of a war in different colours.
