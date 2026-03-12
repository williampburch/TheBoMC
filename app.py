import os
from calendar import month_name
from datetime import datetime
from functools import wraps
from urllib.parse import urlsplit

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
RESTAURANT_STATUS_CHOICES = ["visited", "target", "closed"]

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
    member_profile = db.relationship("Person", back_populates="account", uselist=False)

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
    account_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=True)
    account = db.relationship("User", back_populates="member_profile")
    weights = db.relationship("WeighIn", back_populates="person")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def career_gain(self):
        return round(sum(weight.gain for weight in self.weights), 1)

    @property
    def weigh_in_count(self):
        return len(self.weights)

    @property
    def has_admin_account(self):
        return bool(self.account and self.account.is_admin)


class Restaurant(db.Model):
    __tablename__ = "restaurant"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    street_address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    state = db.Column(db.String(40), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="target")
    notes = db.Column(db.String(500), nullable=True)
    visits = db.relationship("Visit", back_populates="restaurant_ref")

    @property
    def full_address(self):
        parts = [self.street_address, self.city, self.state]
        return ", ".join(part.strip() for part in parts if part and part.strip())

    @property
    def latest_visit(self):
        if not self.visits:
            return None
        return max(self.visits, key=lambda visit: (visit.year, visit.month_number, visit.id))

    @property
    def visit_count(self):
        return len(self.visits)

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None


class Visit(db.Model):
    __tablename__ = "visit"

    id = db.Column("visitid", db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.String(20), nullable=False)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurant.id"), nullable=False)
    restaurant_ref = db.relationship("Restaurant", back_populates="visits")
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
    def restaurant(self):
        return self.restaurant_ref.name if self.restaurant_ref else "Unknown restaurant"

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
    def __init__(self, restaurant, visit_count):
        self.restaurant = restaurant
        self.name = restaurant.name
        self.visit_count = visit_count


class RestaurantRosterRow:
    def __init__(self, restaurant):
        self.restaurant = restaurant
        self.visit_count = restaurant.visit_count
        self.latest_visit = restaurant.latest_visit
        self.coordinates_label = (
            f"{restaurant.latitude:.4f}, {restaurant.longitude:.4f}" if restaurant.has_coordinates else "Coordinates missing"
        )


class PersonLeaderboardRow:
    def __init__(self, person):
        self.person = person
        self.total_gain = person.career_gain
        self.visit_count = len({weight.visit_id for weight in person.weights})


class MemberRosterRow:
    def __init__(self, person):
        self.person = person
        self.account = person.account
        self.weigh_in_count = person.weigh_in_count
        self.is_admin = person.has_admin_account


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
            return redirect(url_for("dashboard"))
        return view_func(*args, **kwargs)

    return wrapped_view


def seed_admin_from_env():
    if os.getenv("SKIP_ADMIN_SEED") == "1":
        return

    admin_username = (os.getenv("ADMIN_USERNAME") or os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD")
    reset_password = os.getenv("ADMIN_RESET_PASSWORD_ON_START") == "1"

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
        should_commit = False
        if not existing_user.is_admin:
            existing_user.is_admin = True
            should_commit = True
        if reset_password:
            existing_user.set_password(admin_password)
            should_commit = True
        if should_commit:
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


def parse_optional_int(value):
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return int(normalized)


def parse_optional_float(value):
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return float(normalized)


def is_safe_redirect_target(target):
    if not target:
        return False

    parsed = urlsplit(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/")


def get_redirect_target(default_endpoint="dashboard"):
    target = request.args.get("next") or request.form.get("next")
    if is_safe_redirect_target(target):
        return target
    return url_for(default_endpoint)


def get_people():
    return Person.query.order_by(func.lower(Person.last_name), func.lower(Person.first_name)).all()


def get_users():
    return User.query.order_by(func.lower(User.username)).all()


def get_restaurants():
    return Restaurant.query.order_by(func.lower(Restaurant.name), func.lower(func.coalesce(Restaurant.city, ""))).all()


def get_member_account_options(current_person=None):
    linked_user_ids = {
        person.account_id for person in Person.query.filter(Person.account_id.isnot(None)).all() if person.account_id
    }
    if current_person and current_person.account_id:
        linked_user_ids.discard(current_person.account_id)

    return [user for user in get_users() if user.id not in linked_user_ids]


def resolve_member_account(account_value, current_person=None):
    try:
        account_id = parse_optional_int(account_value)
    except ValueError:
        return None, "Selected account was invalid."

    if account_id is None:
        return None, None

    account = db.session.get(User, account_id)
    if not account:
        return None, "Selected account was invalid."

    existing_link = Person.query.filter(Person.account_id == account_id)
    if current_person:
        existing_link = existing_link.filter(Person.id != current_person.id)

    if existing_link.first():
        return None, "That account is already linked to another member."

    return account, None


def get_weight_map(visit):
    return {weight.person_id: weight for weight in visit.weights}


def get_restaurant_choices():
    return get_restaurants()


def resolve_restaurant(restaurant_value):
    try:
        restaurant_id = parse_optional_int(restaurant_value)
    except ValueError:
        return None, "Selected restaurant was invalid."

    if restaurant_id is None:
        return None, "Restaurant is required."

    restaurant = db.session.get(Restaurant, restaurant_id)
    if not restaurant:
        return None, "Selected restaurant was invalid."

    return restaurant, None


def normalize_restaurant_status(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in RESTAURANT_STATUS_CHOICES else None


def build_restaurant_roster(restaurants):
    return sorted(
        (RestaurantRosterRow(restaurant) for restaurant in restaurants),
        key=lambda row: (
            0 if row.restaurant.status == "visited" else 1,
            row.restaurant.name.lower(),
            (row.restaurant.city or "").lower(),
        ),
    )


def sort_visits(visits):
    return sorted(
        visits,
        key=lambda visit: (visit.year, visit.month_number, visit.restaurant.lower(), visit.id),
        reverse=True,
    )


def build_guest_leaderboard(people):
    return sorted(
        (PersonLeaderboardRow(person) for person in people),
        key=lambda row: (
            -row.total_gain,
            -row.visit_count,
            row.person.last_name.lower(),
            row.person.first_name.lower(),
        ),
    )


def build_member_roster(people):
    return sorted(
        (MemberRosterRow(person) for person in people),
        key=lambda row: (
            0 if row.is_admin else 1,
            -row.weigh_in_count,
            row.person.last_name.lower(),
            row.person.first_name.lower(),
        ),
    )


def build_restaurant_rollup(visits):
    counts = {}
    for visit in visits:
        if not visit.restaurant_ref:
            continue
        restaurant = visit.restaurant_ref
        counts[restaurant] = counts.get(restaurant, 0) + 1
    return [
        RestaurantSummary(restaurant, count)
        for restaurant, count in sorted(
            counts.items(),
            key=lambda item: item[0].name.lower(),
        )
    ]


def build_map_markers(restaurants):
    markers = []
    for restaurant in restaurants:
        if not restaurant.has_coordinates:
            continue
        latest_visit = restaurant.latest_visit
        markers.append(
            {
                "id": restaurant.id,
                "name": restaurant.name,
                "latitude": restaurant.latitude,
                "longitude": restaurant.longitude,
                "status": restaurant.status,
                "address": restaurant.full_address,
                "notes": restaurant.notes or "",
                "visit_count": restaurant.visit_count,
                "latest_visit": latest_visit.label if latest_visit else "",
            }
        )
    return markers


def build_site_snapshot():
    visits = sort_visits(Visit.query.all())
    people = get_people()
    founders = User.query.filter_by(is_admin=True).order_by(func.lower(User.username)).all()
    restaurants = get_restaurants()
    restaurant_rollup = build_restaurant_rollup(visits)
    total_gain = round(sum(weight.gain for visit in visits for weight in visit.weights), 1)
    latest_visit = visits[0] if visits else None
    guest_leaderboard = build_guest_leaderboard(people)
    member_roster = build_member_roster(people)
    restaurant_roster = build_restaurant_roster(restaurants)
    monthly_trend = [{"label": visit.label, "gain": visit.total_gain} for visit in visits[:6]]
    max_monthly_gain = max((item["gain"] for item in monthly_trend), default=0)
    map_markers = build_map_markers(restaurants)

    return {
        "visits": visits,
        "people": people,
        "founders": founders,
        "restaurants": restaurants,
        "restaurant_rollup": restaurant_rollup,
        "restaurant_roster": restaurant_roster,
        "total_gain": total_gain,
        "latest_visit": latest_visit,
        "guest_leaderboard": guest_leaderboard,
        "top_guest": guest_leaderboard[0] if guest_leaderboard else None,
        "member_roster": member_roster,
        "monthly_trend": monthly_trend,
        "max_monthly_gain": max_monthly_gain,
        "scoreboard": sorted((VisitScoreRow(visit) for visit in visits), key=lambda row: row.total_gain, reverse=True),
        "visit_count": len(visits),
        "people_count": len(people),
        "restaurant_count": len(restaurants),
        "founder_count": len(founders),
        "mapped_restaurant_count": len(map_markers),
        "target_restaurant_count": sum(1 for restaurant in restaurants if restaurant.status == "target"),
        "map_markers": map_markers,
    }


def validate_visit_form():
    if not request.form.get("year", "").strip():
        return "Year is required."
    if not request.form.get("month", "").strip():
        return "Month is required."
    restaurant, restaurant_error = resolve_restaurant(request.form.get("restaurant_id"))
    if restaurant_error:
        return restaurant_error

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


def validate_restaurant_form():
    if not request.form.get("name", "").strip():
        return "Restaurant name is required."

    status = normalize_restaurant_status(request.form.get("status"))
    if not status:
        return "Restaurant status was invalid."

    try:
        latitude = parse_optional_float(request.form.get("latitude"))
        longitude = parse_optional_float(request.form.get("longitude"))
    except ValueError:
        return "Latitude and longitude must be numbers."

    if (latitude is None) != (longitude is None):
        return "Enter both latitude and longitude, or leave both blank."

    if latitude is not None and not (-90 <= latitude <= 90):
        return "Latitude must be between -90 and 90."

    if longitude is not None and not (-180 <= longitude <= 180):
        return "Longitude must be between -180 and 180."

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
        return {
            "month_choices": MONTH_CHOICES,
            "restaurant_status_choices": RESTAURANT_STATUS_CHOICES,
        }

    @app.route("/")
    def home():
        return render_template("home.html", **build_site_snapshot())

    @app.route("/club")
    def club_overview():
        return render_template("club.html", **build_site_snapshot())

    @app.route("/dashboard")
    @login_required
    def dashboard():
        snapshot = build_site_snapshot()
        comments = Comment.query.order_by(Comment.created_at.desc()).limit(12).all()
        return render_template("dashboard.html", comments=comments, **snapshot)

    @app.route("/visits")
    def visits_archive():
        snapshot = build_site_snapshot()
        return render_template("visits.html", visits=snapshot["visits"], scoreboard=snapshot["scoreboard"])

    @app.route("/founders")
    def founders():
        snapshot = build_site_snapshot()
        latest_comments = Comment.query.order_by(Comment.created_at.desc()).limit(12).all()
        return render_template("founders.html", comments=latest_comments, **snapshot)

    @app.route("/guests")
    def guests():
        snapshot = build_site_snapshot()
        return render_template("guests.html", guest_leaderboard=snapshot["guest_leaderboard"])

    @app.route("/map")
    def map_lab():
        snapshot = build_site_snapshot()
        return render_template("map.html", **snapshot)

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        snapshot = build_site_snapshot()
        users = get_users()
        recent_comments = Comment.query.order_by(Comment.created_at.desc()).limit(8).all()
        return render_template(
            "admin_dashboard.html",
            visits=snapshot["visits"][:8],
            member_roster=snapshot["member_roster"],
            people_count=snapshot["people_count"],
            users=users[:6],
            recent_comments=recent_comments,
            user_count=len(users),
            restaurant_count=snapshot["restaurant_count"],
            mapped_restaurant_count=snapshot["mapped_restaurant_count"],
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter(func.lower(User.username) == username).first()
            if user and user.check_password(password):
                login_user(user)
                flash("Signed in.", "success")
                return redirect(get_redirect_target())
            flash("Invalid username or password.", "error")

        return render_template("login.html", next_target=request.args.get("next", ""))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not username or not password:
                flash("Username and password are required.", "error")
                return render_template("register.html", next_target=request.form.get("next", ""))

            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return render_template("register.html", next_target=request.form.get("next", ""))

            if password != confirm_password:
                flash("Passwords did not match.", "error")
                return render_template("register.html", next_target=request.form.get("next", ""))

            if User.query.filter(func.lower(User.username) == username).first():
                flash("A user with that username already exists.", "error")
                return render_template("register.html", next_target=request.form.get("next", ""))

            user = User(username=username, is_admin=False)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Account created. You are now signed in.", "success")
            return redirect(get_redirect_target())

        return render_template("register.html", next_target=request.args.get("next", ""))

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
            return redirect(url_for("dashboard") + "#comments")
        if len(text) > 500:
            flash("Comments must be 500 characters or fewer.", "error")
            return redirect(url_for("dashboard") + "#comments")

        db.session.add(Comment(user_id=current_user.id, comment=text))
        db.session.commit()
        flash("Comment posted.", "success")
        return redirect(url_for("dashboard") + "#comments")

    @app.route("/admin/visit/new", methods=["GET", "POST"])
    @admin_required
    def create_visit():
        people = get_people()
        restaurants = get_restaurant_choices()
        if not people:
            flash("Create at least one member before logging a visit.", "error")
            return redirect(url_for("list_members"))
        if not restaurants:
            flash("Create at least one restaurant before logging a visit.", "error")
            return redirect(url_for("list_restaurants"))

        if request.method == "POST":
            validation_error = validate_visit_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("visit_form.html", visit=None, weight_map={}, people=people, restaurants=restaurants)

            weights, payload_error = build_weight_payload(people)
            if payload_error:
                flash(payload_error, "error")
                return render_template("visit_form.html", visit=None, weight_map={}, people=people, restaurants=restaurants)

            restaurant, _ = resolve_restaurant(request.form.get("restaurant_id"))
            if restaurant.status == "target":
                restaurant.status = "visited"

            visit = Visit(
                year=parse_int(request.form.get("year")),
                month=request.form.get("month"),
                restaurant_ref=restaurant,
            )
            for weight_data in weights:
                visit.weights.append(WeighIn(**weight_data))
            db.session.add(visit)
            db.session.commit()
            flash("Buffet visit created.", "success")
            return redirect(url_for("admin_dashboard"))

        return render_template("visit_form.html", visit=None, weight_map={}, people=people, restaurants=restaurants)

    @app.route("/admin/visit/<int:visit_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_visit(visit_id):
        visit = Visit.query.get_or_404(visit_id)
        people = get_people()
        restaurants = get_restaurant_choices()
        if request.method == "POST":
            validation_error = validate_visit_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template(
                    "visit_form.html",
                    visit=visit,
                    weight_map=get_weight_map(visit),
                    people=people,
                    restaurants=restaurants,
                )

            weights, payload_error = build_weight_payload(people)
            if payload_error:
                flash(payload_error, "error")
                return render_template(
                    "visit_form.html",
                    visit=visit,
                    weight_map=get_weight_map(visit),
                    people=people,
                    restaurants=restaurants,
                )

            restaurant, _ = resolve_restaurant(request.form.get("restaurant_id"))
            if restaurant.status == "target":
                restaurant.status = "visited"

            visit.year = parse_int(request.form.get("year"))
            visit.month = request.form.get("month")
            visit.restaurant_ref = restaurant
            visit.weights.clear()
            for weight_data in weights:
                visit.weights.append(WeighIn(**weight_data))
            db.session.commit()
            flash("Buffet visit updated.", "success")
            return redirect(url_for("admin_dashboard"))

        return render_template("visit_form.html", visit=visit, weight_map=get_weight_map(visit), people=people, restaurants=restaurants)

    @app.route("/admin/visit/<int:visit_id>/delete", methods=["POST"])
    @admin_required
    def delete_visit(visit_id):
        visit = Visit.query.get_or_404(visit_id)
        db.session.delete(visit)
        db.session.commit()
        flash("Buffet visit deleted.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/users/new", methods=["GET", "POST"])
    @admin_required
    def create_user():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            if not username or not password:
                flash("Username and password are required.", "error")
                return render_template("user_form.html", user_account=None)

            if len(password) < 8:
                flash("Passwords must be at least 8 characters.", "error")
                return render_template("user_form.html", user_account=None)

            if User.query.filter(func.lower(User.username) == username).first():
                flash("A user with that username already exists.", "error")
                return render_template("user_form.html", user_account=None)

            user = User(username=username, is_admin=request.form.get("is_admin") == "on")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("User created.", "success")
            return redirect(url_for("list_users"))

        return render_template("user_form.html", user_account=None)

    @app.route("/admin/users")
    @admin_required
    def list_users():
        return render_template("users.html", users=get_users())

    @app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_user(user_id):
        user_account = User.query.get_or_404(user_id)

        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            is_admin = request.form.get("is_admin") == "on"

            if not username:
                flash("Username is required.", "error")
                return render_template("user_form.html", user_account=user_account)

            existing_user = User.query.filter(
                func.lower(User.username) == username,
                User.id != user_account.id,
            ).first()
            if existing_user:
                flash("A user with that username already exists.", "error")
                return render_template("user_form.html", user_account=user_account)

            if user_account.is_admin and not is_admin and User.query.filter_by(is_admin=True).count() == 1:
                flash("At least one admin account must remain.", "error")
                return render_template("user_form.html", user_account=user_account)

            user_account.username = username
            user_account.is_admin = is_admin
            if password:
                if len(password) < 8:
                    flash("Passwords must be at least 8 characters.", "error")
                    return render_template("user_form.html", user_account=user_account)
                user_account.set_password(password)

            db.session.commit()
            flash("User updated.", "success")
            return redirect(url_for("list_users"))

        return render_template("user_form.html", user_account=user_account)

    @app.route("/admin/members")
    @admin_required
    def list_members():
        return render_template("members.html", member_roster=build_member_roster(get_people()))

    @app.route("/admin/restaurants")
    @admin_required
    def list_restaurants():
        return render_template("restaurants.html", restaurant_roster=build_restaurant_roster(get_restaurants()))

    @app.route("/admin/restaurants/new", methods=["GET", "POST"])
    @admin_required
    def create_restaurant():
        if request.method == "POST":
            validation_error = validate_restaurant_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("restaurant_form.html", restaurant=None)

            restaurant = Restaurant(
                name=request.form.get("name", "").strip(),
                street_address=request.form.get("street_address", "").strip() or None,
                city=request.form.get("city", "").strip() or None,
                state=request.form.get("state", "").strip().upper() or None,
                latitude=parse_optional_float(request.form.get("latitude")),
                longitude=parse_optional_float(request.form.get("longitude")),
                status=normalize_restaurant_status(request.form.get("status")),
                notes=request.form.get("notes", "").strip() or None,
            )
            db.session.add(restaurant)
            db.session.commit()
            flash("Restaurant created.", "success")
            return redirect(url_for("list_restaurants"))

        return render_template("restaurant_form.html", restaurant=None)

    @app.route("/admin/restaurants/<int:restaurant_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_restaurant(restaurant_id):
        restaurant = Restaurant.query.get_or_404(restaurant_id)
        if request.method == "POST":
            validation_error = validate_restaurant_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("restaurant_form.html", restaurant=restaurant)

            restaurant.name = request.form.get("name", "").strip()
            restaurant.street_address = request.form.get("street_address", "").strip() or None
            restaurant.city = request.form.get("city", "").strip() or None
            restaurant.state = request.form.get("state", "").strip().upper() or None
            restaurant.latitude = parse_optional_float(request.form.get("latitude"))
            restaurant.longitude = parse_optional_float(request.form.get("longitude"))
            restaurant.status = normalize_restaurant_status(request.form.get("status"))
            restaurant.notes = request.form.get("notes", "").strip() or None
            db.session.commit()
            flash("Restaurant updated.", "success")
            return redirect(url_for("list_restaurants"))

        return render_template("restaurant_form.html", restaurant=restaurant)

    @app.route("/admin/members/new", methods=["GET", "POST"])
    @admin_required
    def create_member():
        account_choices = get_member_account_options()
        if request.method == "POST":
            validation_error = validate_person_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("member_form.html", person=None, account_choices=account_choices)

            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            account, account_error = resolve_member_account(request.form.get("account_id"))
            if account_error:
                flash(account_error, "error")
                return render_template("member_form.html", person=None, account_choices=account_choices)

            existing = Person.query.filter(
                func.lower(Person.first_name) == first_name.lower(),
                func.lower(Person.last_name) == last_name.lower(),
            ).first()
            if existing:
                flash("A member with that name already exists.", "error")
                return render_template("member_form.html", person=None, account_choices=account_choices)

            db.session.add(
                Person(
                    first_name=first_name,
                    last_name=last_name,
                    account_id=account.id if account else None,
                )
            )
            db.session.commit()
            flash("Member created.", "success")
            return redirect(url_for("list_members"))

        return render_template("member_form.html", person=None, account_choices=account_choices)

    @app.route("/admin/members/<int:person_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_member(person_id):
        person = Person.query.get_or_404(person_id)
        account_choices = get_member_account_options(person)
        if request.method == "POST":
            validation_error = validate_person_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template("member_form.html", person=person, account_choices=account_choices)

            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            account, account_error = resolve_member_account(request.form.get("account_id"), current_person=person)
            if account_error:
                flash(account_error, "error")
                return render_template("member_form.html", person=person, account_choices=account_choices)

            existing = Person.query.filter(
                func.lower(Person.first_name) == first_name.lower(),
                func.lower(Person.last_name) == last_name.lower(),
                Person.id != person.id,
            ).first()
            if existing:
                flash("A member with that name already exists.", "error")
                return render_template("member_form.html", person=person, account_choices=account_choices)

            person.first_name = first_name
            person.last_name = last_name
            person.account_id = account.id if account else None
            db.session.commit()
            flash("Member updated.", "success")
            return redirect(url_for("list_members"))

        return render_template("member_form.html", person=person, account_choices=account_choices)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
