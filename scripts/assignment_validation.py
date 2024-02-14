"""
Script to help validate input file before
consumption by ``local_assignment_multi.py``

To use:
```
pip install -r scripts/local_assignment_requirements.txt

python assignment_validation.py print_duplicates --input-file=your-input-file.csv

# or

python assignment_validation.py print_plan_counts --input-file=your-input-file.csv
"""
import csv
from collections import defaultdict, Counter

import click

INPUT_FIELDNAMES = ['email', 'university_name']


def _iterate_csv(input_file):
    with open(input_file, 'r') as f_in:
        reader = csv.DictReader(f_in, fieldnames=INPUT_FIELDNAMES, delimiter=',')
        # read and skip the header
        next(reader, None)
        breakpoint()
        for row in reader:
            yield row


@click.command()
@click.option(
    '--input-file',
    help='Path of local file containing email addresses to assign.',
)
def print_duplicates(input_file):
    unis_by_email = defaultdict(list)
    for row in _iterate_csv(input_file):
        unis_by_email[row['email']].append(row['university_name'])

    for email, uni_list in unis_by_email.items():
        if len(uni_list) > 1:
            print(email, uni_list)


@click.command()
@click.option(
    '--input-file',
    help='Path of local file containing email addresses to assign.',
)
def print_plan_counts(input_file):
    counts_by_plan = Counter()
    for row in _iterate_csv(input_file):
        counts_by_plan[row['university_name']] += 1

    for plan, count in counts_by_plan.items():
        print(plan, count)


@click.group()
def run():
    pass


run.add_command(print_duplicates)
run.add_command(print_plan_counts)


if __name__ == '__main__':
    run()
