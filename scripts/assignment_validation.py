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
from email.utils import parseaddr

import click

INPUT_FIELDNAMES = ['university_name', 'email']


def _iterate_csv(input_file):
    with open(input_file, 'r', encoding='latin-1') as f_in:
        reader = csv.DictReader(f_in, fieldnames=INPUT_FIELDNAMES, delimiter=',')
        # read and skip the header
        next(reader, None)
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
            print(email or 'THE EMPTY STRING', 'is contained in', len(uni_list), 'different rows')


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


def is_valid_email(email):
    _, address = parseaddr(email)
    if not address:
        return False
    return True


@click.command()
@click.option(
    '--input-file',
    help='Path of local file containing email addresses to assign.',
)
def validate_emails(input_file):
    invalid_emails = Counter()
    for row in _iterate_csv(input_file):
        if not is_valid_email(row['email']):
            invalid_emails[row['email']] += 1

    print(f'There were {sum(invalid_emails.values())} invalid emails')
    print(invalid_emails)


@click.group()
def run():
    pass


run.add_command(print_duplicates)
run.add_command(print_plan_counts)
run.add_command(validate_emails)


if __name__ == '__main__':
    run()
