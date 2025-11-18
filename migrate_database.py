"""
Database Migration Script
Run this ONCE to migrate from old schema to new schema
"""

import sqlite3
import os

DB_FILE = 'rental_system.db'
BACKUP_FILE = 'rental_system_backup.db'

def migrate_database():
    print("Starting database migration...")
    
    # Create backup
    if os.path.exists(DB_FILE):
        import shutil
        shutil.copy2(DB_FILE, BACKUP_FILE)
        print(f"✓ Backup created: {BACKUP_FILE}")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Check if migration is needed
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'name' not in columns:
            print("Migrating users table...")
            
            # Add name column
            cursor.execute("ALTER TABLE users ADD COLUMN name VARCHAR(100)")
            
            # Set default name from email
            cursor.execute("""
                UPDATE users 
                SET name = SUBSTR(email, 1, INSTR(email, '@') - 1)
                WHERE name IS NULL
            """)
            
            print("✓ Added 'name' column to users")
        
        if 'phone' not in columns:
            # Add phone column
            cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
            print("✓ Added 'phone' column to users")
        
        # Check products table
        cursor.execute("PRAGMA table_info(products)")
        product_columns = [col[1] for col in cursor.fetchall()]
        
        if 'image_path' not in product_columns:
            cursor.execute("ALTER TABLE products ADD COLUMN image_path VARCHAR(200)")
            print("✓ Added 'image_path' column to products")
        
        # Check if orders table needs migration
        cursor.execute("PRAGMA table_info(orders)")
        order_columns = [col[1] for col in cursor.fetchall()]
        
        if 'customer_name' not in order_columns:
            print("\n⚠ WARNING: Orders table needs major restructuring.")
            print("This migration script handles column additions only.")
            print("For orders table changes, recommend starting fresh.")
            print("\nOptions:")
            print("1. Delete database and start fresh (recommended)")
            print("2. Keep old orders but use new system going forward")
            
            response = input("\nContinue with partial migration? (y/n): ")
            if response.lower() != 'y':
                print("Migration cancelled.")
                conn.close()
                return
        
        conn.commit()
        print("\n✓ Migration completed successfully!")
        print(f"✓ Backup saved as: {BACKUP_FILE}")
        print("\nYou can now run: python app.py")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        print(f"Your original database is backed up as: {BACKUP_FILE}")
        
    finally:
        conn.close()

if __name__ == '__main__':
    print("=" * 50)
    print("Database Migration Tool")
    print("=" * 50)
    print()
    
    if not os.path.exists(DB_FILE):
        print(f"✗ Database file '{DB_FILE}' not found.")
        print("No migration needed. Just run: python app.py")
    else:
        migrate_database()