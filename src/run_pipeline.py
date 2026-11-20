"""Run the reproducible end-to-end analytical pipeline."""
from generate_data import generate_all
from validate_data import validate
from build_segments import build_segments
from analyze_experiment import analyze
from build_cohorts import build_cohorts
from build_forecast import build_forecast
from write_docs import write_docs


if __name__ == "__main__":
    generate_all()
    validate()
    build_segments()
    analyze()
    build_cohorts()
    build_forecast()
    write_docs()
    print("Pipeline completed successfully.")

