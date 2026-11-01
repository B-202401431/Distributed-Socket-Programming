# Integrated three-PC package

- Part1/: exact source files from IT305_Part1_N2(1).zip; N=2 for single and multi modes.
- Part2_Case1/, Part2_Case2/, Part2_Case2_Enhanced/: source from IT305_Fixed(1).zip; N=4 in every Part 2 experiment.
- Tools/experiment.py: startup patch applied; experiment schedule Part1 N=2 and Part2 N=4.
- Tools/lan.py: original all-case three-PC orchestrator.
- Results/local/: pre-existing local results only, NOT fresh three-PC measurements.
- FinalReport_Group_099_107.pdf: original report, unchanged; may describe historical experiment settings.

Build each case with `make -C Part1`, `make -C Part2_Case1`, `make -C Part2_Case2`, `make -C Part2_Case2_Enhanced`.

Read README.md and THREE_PC_TEST_GUIDE.md for WSL/hotspot setup. Run `python3 Tools/lan.py --help` for current CLI.

Note: Part1 N=2 alone does not meet the assignment's throughput-vs-client-count comparison requirement. Additional Part1 client counts should be tested before final academic submission.
