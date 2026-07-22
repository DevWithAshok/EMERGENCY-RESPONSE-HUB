from database import engine, Base

# This triggers the create_all function in database.py
Base.metadata.create_all(bind=engine)
print("Database and tables created successfully!")