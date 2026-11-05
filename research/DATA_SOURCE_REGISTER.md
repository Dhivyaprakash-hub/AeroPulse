# Data and source register

## Primary dataset

**Bureau of Transportation Statistics (BTS), Reporting Carrier On-Time Performance (1987-present), December 2023–August 2026.** The full audit used 33 monthly ZIP archives supplied/downloaded for the study. The CSVs contain 110 columns. The scripts read the archives directly and do not copy or redistribute the flight-level records. The original January–March 2025 sample was used for the initial feasibility audit.

Official dataset description: [BTS TranStats table information](https://www.transtats.bts.gov/TableInfo.asp?QO_fu146_anzr=b0-gvzr&gnoyr_VQ=FGJ). BTS describes scheduled and actual departure/arrival times, cancellations, diversions, delay causes, and distance for reporting carriers. [BTS 2025 Technical Directive No. 39](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time) specifies the reporting scope and relevant fields including the aircraft tail number and local-time records.

The executed chronological experiment uses December 2023 as a linkage warm-up; 2024 for training; 2025 for validation/model selection; and January–August 2026 as the final test. BTS's release page listed August 2026 as the latest available Reporting Carrier On-Time data when this audit was run: [BTS TranStats release information](https://www.transtats.bts.gov/releaseinfo.asp).

## Archive integrity

The submitted ZIPs were read in place. The audit recorded file sizes and archive members in `reports/audit/audit_summary.json`. The ZIP SHA-256 digests are:

| Month | SHA-256 |
|---|---|
| 2025-01 | `868387DCEDAEF1B8D8392E608E642219FDE50D594C3CF2094AEC858167629CCF` |
| 2025-02 | `12DC8DBDB3C8B3C20D4C00A8B188196AE202F781A8760871AE502A9C733D0ECD` |
| 2025-03 | `9C80FBC2112CDBF3F0613EC2001BA019B3AD75511CD69657080736E7EDA9CEF4` |

Data ZIPs were not copied into the repository.

## Coverage and completeness caveat

BTS is a reporting-carrier dataset with regulatory reporting thresholds and geographic scope; it is not a census of every airline movement. The DOT Office of Inspector General found that BTS had procedures intended to find inaccuracies but lacked procedures to verify completeness of carrier-reported data: [DOT OIG report AV2025003](https://www.oig.dot.gov/library-item/46490?page=1). This matters especially for reconstructing aircraft rotations: a missing/non-reported operation can make two reported flights look consecutive when they were not physically consecutive.

## Related benchmark and novelty boundary

The [Aeolus paper (NeurIPS 2025)](https://papers.neurips.cc/paper_files/paper/2025/hash/586fbdff064d506f5af3e3db82681f84-Abstract-Datasets_and_Benchmarks_Track.html) presents a multi-structure delay dataset with more than 50 million flights, flight-chain and network data, temporal splits, and leakage controls. Its paper states the code/data use CC BY-NC 4.0 and academic-research use. See [Aeolus code and data pipeline](https://github.com/Flnny/Delay-data). This establishes that delay propagation and flight chains are not novel topics. AeroPulse should be pitched as an independent, transparent BTS replication/decision-usefulness study, not a new research domain or claimed state-of-the-art method. Review the source dataset terms directly before incorporating any Aeolus data or code.

## Known data limitations

- BTS times are reported in local 24-hour time, not UTC.
- Cancelled and diverted flights lack comparable arrival-delay outcomes and are excluded from the primary regression cohort.
- The December 2023 start boundary left-censors any November 2023 previous leg for flights near the beginning of the study window. December is used as a warm-up; January 2024 onward forms the model periods.
- Reporting omissions, tail-number errors, ferry/maintenance flights and codeshare reporting can interrupt or distort an observed chain.
- `ArrDelay` describes arrival performance relative to schedule; it is not the same as passenger-level disruption or airline recovery cost.
- The expanded scan found one duplicated candidate flight-key group by 64-bit hash. Exact full-row duplicate checking was performed on the Q1 2025 pilot, not repeated across all 33 months. Early HHMM audit output counted the special `2400` midnight notation as invalid; the parsers were corrected to handle it before the sequence reconstruction.
