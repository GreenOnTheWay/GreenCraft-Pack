# GreenCraft v2

Automatycznie zarządzany, prywatnie projektowany modpack do normalnego grania.

## Architektura

- Prism Launcher
- Fabric
- packwiz / packwiz-installer
- `stable/` = jedyna wersja używana przez normalnego gracza
- `candidate/` = nowy Minecraft w trakcie walidacji
- GitHub-hosted CI = zależności + dedicated-server smoke test
- lokalny RTX 4070 Ti validator = test Iris/shadera w prawdziwym renderingu

## Ważne

Repo może być publiczne, bo nie zawiera sekretów ani danych gracza.
Nie podpinaj do niego self-hosted GitHub Runnera. GPU test działa lokalnie przez `scripts/gpu_validate.ps1`.

`Distant Horizons` jest wyłączony w baseline v2.0 i może wrócić dopiero jako osobno zatwierdzony moduł.

Normalny klient czyta wyłącznie:

`stable/pack.toml`
