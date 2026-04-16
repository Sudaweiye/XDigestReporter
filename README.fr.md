# Guide d'utilisation de XDigestReporter

## Fonctionnalités
- Sélection des comptes X à suivre.
- Récupération uniquement des tweets du jour (fuseau Asia/Shanghai), jusqu'à 20 tweets par compte.
- Stratégie d'économie d'appels X API :
  - Cache local `user_id` (évite les recherches répétées)
  - Résolution des noms d'utilisateur en lot (jusqu'à 100 par requête)
  - Récupération incrémentale du jour via `since_id` (seulement les nouveaux tweets)
- Sortie de chaque tweet : texte original + traduction en chinois simplifié.
- Utilisation de GPT-5.3-Codex pour le résumé, l'évaluation et les sujets clés par compte.
- Génération d'une synthèse globale des tendances.
- Génération simultanée d'un rapport Markdown et d'un PDF compilé avec LaTeX.
- Exécution planifiée quotidienne (Planificateur de tâches Windows).
- Contrôle du budget X API selon le coût estimé par requête.

## Prérequis
- X Bearer Token
- Commande locale `codex` disponible et authentifiée
- Modèle par défaut : `gpt-5.3-codex`
- Compilateur LaTeX installé (TeX Live recommandé, `xelatex` requis dans le PATH)

## Exécution
1. Ouvrir `XDigestReporter.exe`
2. Renseigner le token X (pas besoin de clé OpenAI API)
3. Sélectionner les comptes
4. Cliquer sur « Générer le rapport maintenant »

Répertoire de sortie : `dist/reports/`

Chaque exécution génère 3 fichiers (même nom, extensions différentes) :
- `x_digest_*.md`
- `x_digest_*.tex`
- `x_digest_*.pdf` (compilé par LaTeX, avec date et filigrane `Jinge Guo專用`)

## Build
```powershell
cd E:\XDigestReporter
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Exécutable : `E:\XDigestReporter\dist\XDigestReporter.exe`
