from django.core.management.base import BaseCommand

from checkin.models import Attendee

SEED_ATTENDEES = [
    {"name": "Ada Lovelace", "qr_code": "QR-ADA-001"},
    {"name": "Grace Hopper", "qr_code": "QR-GRACE-002"},
    {"name": "Alan Turing", "qr_code": "QR-ALAN-003"},
]


class Command(BaseCommand):
    help = "Seed the database with 3 demo attendees for the check-in kiosk."

    def handle(self, *args, **options):
        created_count = 0
        for entry in SEED_ATTENDEES:
            _, created = Attendee.objects.get_or_create(
                qr_code=entry["qr_code"], defaults={"name": entry["name"]}
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created attendee: {entry['name']} ({entry['qr_code']})"))
            else:
                self.stdout.write(f"Attendee already exists: {entry['name']} ({entry['qr_code']})")

        self.stdout.write(self.style.SUCCESS(f"Done. {created_count} new attendee(s) created."))
