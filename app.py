import os
from calendar import month_name
from datetime import datetime
from functools import wraps

import bcrypt
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.security import check_password_hash


load_dotenv()

MONTH_CHOICES = [month_name[index] for index in range(1, 13)]
MONTH_TO_NUMBER = {name: index for index, name in enumerate(MONTH_CHOICES, start=1)}

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column("password", db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_admin = db.Column("administrator", db.Boolean, nullable=False, default=False)
    comments = db.relationship("Comment", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def check_password(self, password):
        normalized_hash = self.password_hash
        if normalized_hash.startswith("$2y$"):
            normalized_hash = "$2b$" + normalized_hash[4:]

        if normalized_hash.startswith("$2a$") or normalized_hash.startswith("$2b$"):
            try:
                return bcrypt.checkpw(password.encode("utf-8"), normalized_hash.encode("utf-8"))
            except ValueError:
                return False

        try:
            return check_password_hash(self.password_hash, password)
        except (ValueError, TypeError):
            return False


class Person(db.Model):
    __tablename__ = "person"
    __table_args__ = (UniqueConstraint("first_name", "last_name", name="uq_person_name"),)

    id = db.Column("personid", db.Integer, primary_key=True)
    first_name = db.Column(db.String(255), nullable=False)
    last_name = db.Column(db.String(255), nullable=False)
    weights = db.relationship("WeighIn", back_populates="person")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def career_gain(self):
        return round(sum(weight.gain for weight in self.weights), 1)


class Visit(db.Model):
    __tablename__ = "visit"

    id = db.Column("visitid", db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.String(20), nullable=False)
    restaurant = db.Column(db.String(255), nullable=False)
    weights = db.relationship(
        "WeighIn",
        back_populates="visit",
        cascade="all, delete-orphan",
        order_by="WeighIn.person_id",
    )

    @property
    def month_number(self):
        return MONTH_TO_NUMBER.get(self.month, 0)

    @property
    def label(self):
        return f"{self.month} {self.year}"

    @property
    def total_gain(self):
        return round(sum(weight.gain for weight in self.weights), 1)


class WeighIn(db.Model):
    __tablename__ = "weight"

    id = db.Column("weightid", db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.personid"), nullable=False)
    visit_id = db.Column(db.Integer, db.ForeignKey("visit.visitid"), nullable=False)
    before_weight = db.Column("preweight", db.Float, nullable=False)
    after_weight = db.Column("postweight", db.Float, nullable=False)
    person = db.relationship("Person", back_populates="weights")
    visit = db.relationship("Visit", back_populates="weights")

    @property
    def gain(self):
        return round(self.after_weight - self.before_weight, 1)


class Comment(db.Model):
    __tablename__ = "comment"

    id = db.Column("commentid", db.Integer, primary_key=True)
    user_id = db.Column("userid", db.Integer, db.ForeignKey("user.id"), nullable=False)
    comment = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship("User", back_populates="comments")


class VisitScoreRow:
    def __init__(self, visit):
        self.visit = visit
        self.total_gain = visit.total_gain


class RestaurantSummary:
    def __init__(self, name, visit_count):
        self.name = name
        self.visit_count = visit_count


class PersonLeaderboardRow:
    def __init__(self, person):
        self.person = person
        self.total_gain = person.career_gain
        self.visit_count = len({weight.visit_id for weight in person.weights})


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///buffet_club.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    instance_path = os.path.join(app.root_path, "instance")
    os.makedirs(instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    with app.app_context():
        seed_admin_from_env()

    register_routes(app)
    return app


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not current_user.is_admin:
            flash("Admin access is required.", "error")
            return redirect(url_for("home"))
        return view_func(*args, **kwargs)

    return wrapped_view


def seed_admin_from_env():
    if os.getenv("SKIP_ADMIN_SEED") == "1":
        return

    admin_username = (os.getenv("ADMIN_USERNAME") or os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_username or not admin_password:
        return

    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return

    try:
        existing_user = User.query.filter(func.lower(User.username) == admin_username).first()
    except OperationalError:
        return

    if existing_user:
        if not existing_user.is_admin:
            existing_user.is_admin = True
            db.session.commit()
        return

    user = User(username=admin_username, is_admin=True)
    user.set_password(admin_password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def parse_float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def parse_int(value):
    return int(str(value).strip())


def get_people():
    return Person.query.order_by(func.lower(Person.last_name), func.lower(Person.first_name)).all()


def get_weight_map(visit):
    return {weight.person_id: weight for weight in visit.weights}


def sort_visits(visits):
    return sorted(
        visits,
        key=lambda visit: (visit.year, visit.month_number, visit.restaurant.lower(), visit.id),
        reverse=True,
    )


def build_restaurant_rollup(visits):
    counts = {}
    for visit in visits:
        counts[visit.restaurant] = counts.get(visit.restaurant, 0) + 1
    return [RestaurantSummary(name, count) for name, count in sorted(counts.items(), key=lambda item: item[0].lower())]


def validate_visit_form():
    if not request.form.get("year", "").strip():
        return "Year is required."
    if not request.form.get("month", "").strip():
        return "Month is required."
    if not request.form.get("restaurant", "").strip():
        return "Restaurant is required."

    try:
        year = parse_int(request.form.get("year"))
    except ValueError:
        return "Year must be a number."

    if year < 1900 or year > 2100:
        return "Year must be between 1900 and 2100."

    if request.form.get("month") not in MONTH_CHOICES:
        return "Month selection was invalid."

    return None


def validate_person_form():
    if not request.form.get("first_name", "").strip():
        return "First name is required."
    if not request.form.get("last_name", "").strip():
        return "Last name is required."
    return None


def build_weight_payload(people):
    weights = []
    for person in people:
        before_value = request.form.get(f"before_{person.id}", "").strip()
        after_value = request.form.get(f"after_{person.id}", "").strip()
        if not before_value and not after_value:
            continue
        if not before_value or not after_value:
            return None, f"Both before and after weights are required for {person.full_name}."
        weights.append(
            {
                "person_id": person.id,
                "before_weight": parse_float(before_value),
                "after_weight": parse_float(after_value),
            }
        )

    if not weights:
        return None, "Enter at least one weigh-in for the visit."

    return weights, None


def register_routes(app):
    @app.context_processor
    def inject_defaults():
        return {"month_choices": MONTH_CHOICES}

    @app.route("/")
    def home():
        visits = sort_visits(Visit.query.all())
        people = get_people()
        founders = User.query.filter_by(is_admin=True).order_by(func.lower(User.username)).all()
        comments = Comment.query.order_by(Comment.created_at.desc()).limit(12).all()
        restaurant_rollup = build_restaurant_rollup(visits)
        total_gain = round(sum(weight.gain for visit in visits for weight in visit.weights), 1)
        scoreboard = sorted((VisitScoreRow(visit) for visit in visits), key=lambda row: row.total_gain, reverse=True)
        latest_visit = visits[0] if visits else None
        guest_leaderboard = sorted(
            (PersonLeaderboardRow(person) for person in people),
            key=lambda row: row.total_gain,
            reverse=True,
        )
        monthly_trend = [
            {"label": visit.label, "gain": visit.total_gain}
            for visit in visits[:6]
        ]
        max_monthly_gain = max((item["gain"] for item in monthly_trend), default=0)
        top_guest = guest_leaderboard[0] if guest_leaderboard else None

        return render_template(
            "home.html",
            visits=visits,
            people=people,
            founders=founders,
            comments=comments,
            scoreboard=scoreboard,
            latest_visit=latest_visit,
            top_guest=top_guest,
            guest_leaderboard=guest_leaderboard,
            monthly_trend=monthly_trend,
            max_monthly_gain=max_monthly_gain,
            restaurant_rollup=restaurant_rollup,
            visit_count=len(visits),
            restaurant_count=len(restaurant_rollup),
            total_gain=total_gain,
        )

    @app.route("/visits")
    def visits_archive():
        visits = sort_visits(Visit.query.all())
        scoreboard = sorted((VisitScoreRow(visit) for visit in visits), key=lambda row: row.total_gain, reverse=True)
        return render_template("visits.html", visits=visits, scoreboard=scoreboard)

    @app.route("/founders")
    def founders():
        founders = User.query.filter_by(is_admin=True).order_by(func.lower(User.username)).all()
        latest_comments = Comment.query.order_by(Comment.created_at.desc()).limit(12).all()
        return render_template("founders.html", founders=founders, comments=latest_comments)

    @app.route("/guests")
    def guests():
        people = get_people()
        guest_leaderboard = sorted(
            (PersonLeaderboardRow(person) for person in people),
            key=lambda row: row.total_gain,
            reverse=True,
        )
        return render_template("guests.html", guest_leaderboard=guest_leaderboard)

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        visits = sort_visits(Visit.query.all())
        people = get_people()
        recent_comments = Comment.query.order_by(Comment.created_at.desc()).limit(8).all()
        return render_template(
            "admin_dashboard.html",
            visits=visits[:8],
            people=people,
            recent_comments=recent_comments,
            user_count=User.query.count(),
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("home"))

        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter(func.lower(User.username) == username).first()
            if user and user.check_password(password):
                login_user(user)
                flash("Signed in.", "success")
                return redirect(url_for("home"))
            flash("Invalid username or password.", "error")

        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        flash("Signed out.", "success")
        return redirect(url_for("home"))

    @app.route("/comments", methods=["POST"])
    @login_required
    def create_comment():
        text = request.form.get("comment", "").strip()
        if not text:
            flash("Comment text is required.", "error")
            return redirect(url_for("home") + "#comments")
        if len(text) > 500:
            flash("Comments must be 500 characters or fewer.", "error")
            return redirect(url_for("home") + "#comments")

        db.session.add(Comment(user_id=current_user.id, comment=text))
        db.session.commit()
        flash("Comment posted.", "success")
        return redirect(url_for("home") + "#comments")

    @app.route("/admin/visit/new", methods=["GET", "POST"])
    @admin_required
    def create_visit():
        people = get_people()
        if not people:
            flash("Create at least one member before logging a visit.", "error")
            return redirect(url_for("list_members"))

        if request.method == "POST":
            validation_error = validate_visit_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("visit_form.html", visit=None, weight_map={}, people=people)

            weights, payload_error = build_weight_payload(people)
            if payload_error:
                flash(payload_error, "error")
                return render_template("visit_form.html", visit=None, weight_map={}, people=people)

            visit = Visit(
                year=parse_int(request.form.get("year")),
                month=request.form.get("month"),
                restaurant=request.form.get("restaurant", "").strip(),
            )
            for weight_data in weights:
                visit.weights.append(WeighIn(**weight_data))
            db.session.add(visit)
            db.session.commit()
            flash("Buffet visit created.", "success")
            return redirect(url_for("home"))

        return render_template("visit_form.html", visit=None, weight_map={}, people=people)

    @app.route("/admin/visit/<int:visit_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_visit(visit_id):
        visit = Visit.query.get_or_404(visit_id)
        people = get_people()
        if request.method == "POST":
            validation_error = validate_visit_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("visit_form.html", visit=visit, weight_map=get_weight_map(visit), people=people)

            weights, payload_error = build_weight_payload(people)
            if payload_error:
                flash(payload_error, "error")
                return render_template("visit_form.html", visit=visit, weight_map=get_weight_map(visit), people=people)

            visit.year = parse_int(request.form.get("year"))
            visit.month = request.form.get("month")
            visit.restaurant = request.form.get("restaurant", "").strip()
            visit.weights.clear()
            for weight_data in weights:
                visit.weights.append(WeighIn(**weight_data))
            db.session.commit()
            flash("Buffet visit updated.", "success")
            return redirect(url_for("home"))

        return render_template("visit_form.html", visit=visit, weight_map=get_weight_map(visit), people=people)

    @app.route("/admin/visit/<int:visit_id>/delete", methods=["POST"])
    @admin_required
    def delete_visit(visit_id):
        visit = Visit.query.get_or_404(visit_id)
        db.session.delete(visit)
        db.session.commit()
        flash("Buffet visit deleted.", "success")
        return redirect(url_for("home"))

    @app.route("/admin/users/new", methods=["GET", "POST"])
    @admin_required
    def create_user():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            if not username or not password:
                flash("Username and password are required.", "error")
                return render_template("user_form.html")

            if User.query.filter(func.lower(User.username) == username).first():
                flash("A user with that username already exists.", "error")
                return render_template("user_form.html")

            user = User(username=username, is_admin=request.form.get("is_admin") == "on")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("User created.", "success")
            return redirect(url_for("home"))

        return render_template("user_form.html")

    @app.route("/admin/members")
    @admin_required
    def list_members():
        people = get_people()
        return render_template("members.html", people=people)

    @app.route("/admin/members/new", methods=["GET", "POST"])
    @admin_required
    def create_member():
        if request.method == "POST":
            validation_error = validate_person_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("member_form.html", person=None)

            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            existing = Person.query.filter(
                func.lower(Person.first_name) == first_name.lower(),
                func.lower(Person.last_name) == last_name.lower(),
            ).first()
            if existing:
                flash("A member with that name already exists.", "error")
                return render_template("member_form.html", person=None)

            db.session.add(Person(first_name=first_name, last_name=last_name))
            db.session.commit()
            flash("Member created.", "success")
            return redirect(url_for("list_members"))

        return render_template("member_form.html", person=None)

    @app.route("/admin/members/<int:person_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_member(person_id):
        person = Person.query.get_or_404(person_id)
        if request.method == "POST":
            validation_error = validate_person_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("member_form.html", person=person)

            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            existing = Person.query.filter(
                func.lower(Person.first_name) == first_name.lower(),
                func.lower(Person.last_name) == last_name.lower(),
                Person.id != person.id,
            ).first()
            if existing:
                flash("A member with that name already exists.", "error")
                return render_template("member_form.html", person=person)

            person.first_name = first_name
            person.last_name = last_name
            db.session.commit()
            flash("Member updated.", "success")
            return redirect(url_for("list_members"))

        return render_template("member_form.html", person=person)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
