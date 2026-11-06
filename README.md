# EMEP_BIAS

Independent research project: predict the **next-year EMEP model bias** for NO₂, O₃ and PM₂.₅, then reconstruct the bias over **every grid cell**. This is not the FAIRMODE fixed-baseline approach.

## Data audit (initial stage)

**Station dataset:** derived EEA-based annual observations for **2015–2023**, archived on [Zenodo (DOI: 10.5281/zenodo.17085064)](https://zenodo.org/records/17085064). We download and convert the annual GeoParquet into a reviewable CSV containing observed concentrations, station IDs, location, type and annual coverage, **without filling missing station-years**. This dataset includes gap-filling for PM₂.₅ in its production pipeline: it is a *pilot*, not the final unmodified verified observation benchmark. The final dataset should be independently checked against the [EEA E1a verified data](https://eeadmz1-downloads-webapp.azurewebsites.net/).

**EMEP dataset:** [EMEP/MSC-W outputs](https://emep.int/mscw/mscw_moddata.html) from [MET Norway THREDDS](https://thredds.met.no/thredds/catalog/data/EMEP/2024_Reporting/catalog.html). The catalogue script inventories *actual* model files and metadata. Do **not** combine reporting years or model versions indiscriminately: different model versions, grids, emissions and variable definitions can introduce artificial changes in bias.

**Status:** raw source files are not stored in git. Station CSV and EMEP catalogue can be generated automatically by the GitHub Actions workflow, subject to successful downloads and GitHub permissions. **No paired training data are claimed until matching and unit checks succeed.**

## Run

```bash
python -m pip install -r requirements.txt
python scripts/download_eea.py --output data/processed/eea_stations_annual_2015_2023.csv
python scripts/discover_emep.py --output data/metadata/emep_catalog_2024_reporting.csv
# once consistent annual EMEP files are available:
python scripts/match_stations.py --help
```

Open the [GitHub Actions tab](https://github.com/costpetrides/EMEP_BIAS/actions) and inspect **Bootstrap observations and EMEP catalogue**. Dataset downloads and generated CSV must be verified in the workflow logs; adding a workflow does not mean the downloads ran.

## Planned analysis

- **M1:** Temporal neural model at stations + IDW or kriging.
- **M2:** Masked spatiotemporal model for full-grid prediction with missing station-years.
- **M3:** Temporal ML + learned diffusion PDE for spatial regularisation. A bias-diffusion PDE is a *mathematical reconstruction prior*, not a physical law of atmospheric transport.

For all methods: predict strictly **one year ahead**; keep target-year observations out of training; evaluate temporally and on **wholly held-out stations**. Match the spatial and temporal aggregation and units. Especially: **ppb O₃ cannot be compared directly with µg/m³ observations**, and EMEP PM₂.₅ at RH50 requires interpretation.

## Attribution

Observations: European Environment Agency; derived dataset by Johannes Heisig / Open-Earth-Monitor, [Zenodo](https://doi.org/10.5281/zenodo.17085064). Model data: EMEP/MSC-W and MET Norway. Retain source names, checksums, downloaded time and licenses.
