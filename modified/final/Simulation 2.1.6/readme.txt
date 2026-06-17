Siulation 2.1.5 Fix(Hop Reduction Fixed)

1. Hop Reduction Formula Corrected
- Now using: (Original Hop Count - Actual Hop Count) / Original Hop Count
- Provides accurate measurement of hop savings.
- Fixes the previous issue where hop reduction appeared flat.

2. Latency Calculation Improved
- Ensures latency values are normalized across different iterations.

3. run_simulation() Function Enhanced
- Properly tracks original and actual hop counts for each Interest Packet.
- Correctly computes simulation metrics at each iteration:
    - Total Requests
    - Cache Hits
    - Cache Hit Ratio
    - Hop Reduction
    - Average Latency

Conclusion
- The simulation framework is now fully ready for experiments on caching policies.
- Results are accurate, visually meaningful, and aligned with research objectives.
