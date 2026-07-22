from models_and_auth import SessionLocal, Hospital, User, get_password_hash

db = SessionLocal()

try:
    admin_user = db.query(User).filter(User.username == "admin").first()
    if not admin_user:
        hashed_pw = get_password_hash("admin123")
        admin_user = User(username="admin", hashed_password=hashed_pw, role="HOSPITAL_ADMIN")
        db.add(admin_user)

    hospital = db.query(Hospital).filter(Hospital.id == 1).first()
    if not hospital:
        test_hospital = Hospital(id=1, name="City General", icu_beds_available=10, general_beds_available=50)
        db.add(test_hospital)

    db.commit()
    print("✅ Secure User and Hospital added to the new database!")
except Exception as e:
    print(f"❌ Error inserting data: {e}")
finally:
    db.close()