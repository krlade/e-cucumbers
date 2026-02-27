from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth.models import User
from django.db.utils import OperationalError
import sys

class Command(BaseCommand):
    help = 'Wykonywanie inicjalizacji środowiska bazy danych (Migracje + SuperUser)'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.NOTICE('==== Rozpoczynanie konfiguracji E-Cucumbers ===='))
        
        try:
            self.stdout.write('1. Aplikowanie migracji...')
            call_command('migrate')
            self.stdout.write(self.style.SUCCESS('Pomyślnie zmigrowano schematy bazodanowe.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Błąd podczas wykonywania migracji: {e}'))
            sys.exit(1)
            
        try:
            self.stdout.write('2. Weryfikacja konta admin (Root)...')
            if not User.objects.filter(username="admin").exists():
                User.objects.create_superuser("admin", "admin@ecucumbers.com", "admin123")
                self.stdout.write(self.style.SUCCESS('Utworzono bazowe konto głównego inżyniera (admin:admin123).'))
            else:
                self.stdout.write(self.style.WARNING('Konto administratora głównego już istnieje, pomijanie...'))
                
        except OperationalError:
            self.stdout.write(self.style.ERROR('Błąd połącznia z tabelą użytkowników, zła struktura migracji.'))
            sys.exit(1)
            
        self.stdout.write(self.style.SUCCESS('\n==== Gotowe! Baza danych została oporządzona i jest gotowa do uruchomienia. ===='))
