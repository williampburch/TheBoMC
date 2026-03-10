import os
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from sqlalchemy import func
from sqlalchemy.exc import OperationalError
from werkzeug.security import check_password_hash, generate_password_hash


load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Restaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    city = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    visits = db.relationship("BuffetVisit", back_populates="restaurant")


class ClubMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    weigh_ins = db.relationship("WeighIn", back_populates="member")


class BuffetVisit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurant.id"), nullable=False)
    visit_date = db.Column(db.Date, nullable=False)
    price_per_person = db.Column(db.Float, nullable=False)
    overall_rating = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    restaurant = db.relationship("Restaurant", back_populates="visits")
    weigh_ins = db.relationship(
        "WeighIn",
        back_populates="visit",
        cascade="all, delete-orphan",
        order_by="WeighIn.member_id",
    )


class WeighIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("buffet_visit.id"), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("club_member.id"), nullable=False)
    before_weight = db.Column(db.Float, nullable=False)
    after_weight = db.Column(db.Float, nullable=False)
    visit = db.relationship("BuffetVisit", back_populates="weigh_ins")
    member = db.relationship("ClubMember", back_populates="weigh_ins")

    @property
    def gain(self):
        return round(self.after_weight - self.before_weight, 1)


class VisitScoreRow:
    def __init__(self, visit):
        self.visit = visit
        self.total_gain = round(sum(weigh_in.gain for weigh_in in visit.weigh_ins), 1)


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
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_name = os.getenv("ADMIN_NAME", "Club Commissioner")

    if not admin_email or not admin_password:
        return

    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return

    try:
        existing_user = User.query.filter_by(email=admin_email.lower()).first()
    except OperationalError:
        return

    if existing_user:
        return

    db.session.add(
        User(
            email=admin_email.lower(),
            password_hash=generate_password_hash(admin_password),
            display_name=admin_name,
            is_admin=True,
        )
    )
    db.session.commit()


def parse_float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def get_active_members():
    return ClubMember.query.filter_by(active=True).order_by(ClubMember.name.asc()).all()


def get_available_restaurants():
    return Restaurant.query.order_by(Restaurant.active.desc(), Restaurant.name.asc()).all()


def get_weigh_in_map(visit):
    return {weigh_in.member_id: weigh_in for weigh_in in visit.weigh_ins}


def validate_visit_form():
    required_fields = {
        "restaurant_id": "Restaurant is required.",
        "visit_date": "Visit date is required.",
        "price_per_person": "Price per person is required.",
        "overall_rating": "Overall rating is required.",
        "notes": "Visit notes are required.",
    }

    for field_name, error_message in required_fields.items():
        if not request.form.get(field_name, "").strip():
            return error_message

    try:
        parse_date(request.form.get("visit_date"))
    except ValueError:
        return "Visit date must use the YYYY-MM-DD format."

    restaurant = db.session.get(Restaurant, int(request.form.get("restaurant_id")))
    if not restaurant:
        return "Selected restaurant was not found."

    return None


def validate_named_record(field_name, model_name):
    if not request.form.get(field_name, "").strip():
        return f"{model_name} name is required."
    return None


def build_weigh_in_payload(members):
    weigh_ins = []
    for member in members:
        before_value = request.form.get(f"before_{member.id}", "").strip()
        after_value = request.form.get(f"after_{member.id}", "").strip()
        if not before_value or not after_value:
            continue
        weigh_ins.append(
            {
                "member_id": member.id,
                "before_weight": parse_float(before_value),
                "after_weight": parse_float(after_value),
            }
        )
    return weigh_ins


def register_routes(app):
    @app.context_processor
    def inject_defaults():
        return {
            "club_members": ClubMember.query.order_by(ClubMember.active.desc(), ClubMember.name.asc()).all()
        }

    @app.route("/")
    def home():
        visits = BuffetVisit.query.order_by(BuffetVisit.visit_date.desc()).all()
        restaurants = Restaurant.query.order_by(Restaurant.name.asc()).all()
        members = ClubMember.query.order_by(ClubMember.active.desc(), ClubMember.name.asc()).all()
        visit_count = len(visits)
        average_rating = db.session.query(func.avg(BuffetVisit.overall_rating)).scalar() or 0
        average_price = db.session.query(func.avg(BuffetVisit.price_per_person)).scalar() or 0
        total_gain = db.session.query(func.sum(WeighIn.after_weight - WeighIn.before_weight)).scalar() or 0
        scoreboard = sorted((VisitScoreRow(visit) for visit in visits), key=lambda row: row.total_gain, reverse=True)
        return render_template(
            "home.html",
            visits=visits,
            restaurants=restaurants,
            members=members,
            scoreboard=scoreboard,
            visit_count=visit_count,
            average_rating=round(average_rating, 1),
            average_price=round(average_price, 2),
            total_gain=round(total_gain, 1),
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("home"))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                flash("Signed in.", "success")
                return redirect(url_for("home"))
            flash("Invalid email or password.", "error")

        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        flash("Signed out.", "success")
        return redirect(url_for("home"))

    @app.route("/admin/visit/new", methods=["GET", "POST"])
    @admin_required
    def create_visit():
        members = get_active_members()
        restaurants = get_available_restaurants()
        if not members:
            flash("Create at least one active member before logging a visit.", "error")
            return redirect(url_for("list_members"))
        if not restaurants:
            flash("Create at least one restaurant before logging a visit.", "error")
            return redirect(url_for("list_restaurants"))

        if request.method == "POST":
            validation_error = validate_visit_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template(
                    "visit_form.html",
                    visit=None,
                    weigh_in_map={},
                    members=members,
                    restaurants=restaurants,
                )

            visit = BuffetVisit(
                restaurant_id=int(request.form.get("restaurant_id")),
                visit_date=parse_date(request.form.get("visit_date")),
                price_per_person=parse_float(request.form.get("price_per_person")),
                overall_rating=parse_float(request.form.get("overall_rating")),
                notes=request.form.get("notes", "").strip(),
            )
            for weigh_in_data in build_weigh_in_payload(members):
                visit.weigh_ins.append(WeighIn(**weigh_in_data))
            db.session.add(visit)
            db.session.commit()
            flash("Buffet visit created.", "success")
            return redirect(url_for("home"))

        return render_template(
            "visit_form.html",
            visit=None,
            weigh_in_map={},
            members=members,
            restaurants=restaurants,
        )

    @app.route("/admin/visit/<int:visit_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_visit(visit_id):
        visit = BuffetVisit.query.get_or_404(visit_id)
        members = get_active_members()
        restaurants = get_available_restaurants()
        if request.method == "POST":
            validation_error = validate_visit_form()
            if validation_error:
                flash(validation_error, "error")
                return render_template(
                    "visit_form.html",
                    visit=visit,
                    weigh_in_map=get_weigh_in_map(visit),
                    members=members,
                    restaurants=restaurants,
                )

            visit.restaurant_id = int(request.form.get("restaurant_id"))
            visit.visit_date = parse_date(request.form.get("visit_date"))
            visit.price_per_person = parse_float(request.form.get("price_per_person"))
            visit.overall_rating = parse_float(request.form.get("overall_rating"))
            visit.notes = request.form.get("notes", "").strip()
            visit.weigh_ins.clear()
            for weigh_in_data in build_weigh_in_payload(members):
                visit.weigh_ins.append(WeighIn(**weigh_in_data))

            db.session.commit()
            flash("Buffet visit updated.", "success")
            return redirect(url_for("home"))

        return render_template(
            "visit_form.html",
            visit=visit,
            weigh_in_map=get_weigh_in_map(visit),
            members=members,
            restaurants=restaurants,
        )

    @app.route("/admin/visit/<int:visit_id>/delete", methods=["POST"])
    @admin_required
    def delete_visit(visit_id):
        visit = BuffetVisit.query.get_or_404(visit_id)
        db.session.delete(visit)
        db.session.commit()
        flash("Buffet visit deleted.", "success")
        return redirect(url_for("home"))

    @app.route("/admin/users/new", methods=["GET", "POST"])
    @admin_required
    def create_user():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            display_name = request.form.get("display_name", "").strip()

            if User.query.filter_by(email=email).first():
                flash("A user with that email already exists.", "error")
                return redirect(url_for("create_user"))

            db.session.add(
                User(
                    email=email,
                    password_hash=generate_password_hash(password),
                    display_name=display_name,
                    is_admin=True,
                )
            )
            db.session.commit()
            flash("Admin user created.", "success")
            return redirect(url_for("home"))

        return render_template("user_form.html")

    @app.route("/admin/members")
    @admin_required
    def list_members():
        members = ClubMember.query.order_by(ClubMember.active.desc(), ClubMember.name.asc()).all()
        return render_template("members.html", members=members)

    @app.route("/admin/members/new", methods=["GET", "POST"])
    @admin_required
    def create_member():
        if request.method == "POST":
            validation_error = validate_named_record("name", "Member")
            if validation_error:
                flash(validation_error, "error")
                return render_template("member_form.html", member=None)

            name = request.form.get("name", "").strip()
            if ClubMember.query.filter(func.lower(ClubMember.name) == name.lower()).first():
                flash("A member with that name already exists.", "error")
                return render_template("member_form.html", member=None)

            db.session.add(ClubMember(name=name, active=request.form.get("active") == "on"))
            db.session.commit()
            flash("Member created.", "success")
            return redirect(url_for("list_members"))

        return render_template("member_form.html", member=None)

    @app.route("/admin/members/<int:member_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_member(member_id):
        member = ClubMember.query.get_or_404(member_id)
        if request.method == "POST":
            validation_error = validate_named_record("name", "Member")
            if validation_error:
                flash(validation_error, "error")
                return render_template("member_form.html", member=member)

            name = request.form.get("name", "").strip()
            existing = ClubMember.query.filter(func.lower(ClubMember.name) == name.lower(), ClubMember.id != member.id).first()
            if existing:
                flash("A member with that name already exists.", "error")
                return render_template("member_form.html", member=member)

            member.name = name
            member.active = request.form.get("active") == "on"
            db.session.commit()
            flash("Member updated.", "success")
            return redirect(url_for("list_members"))

        return render_template("member_form.html", member=member)

    @app.route("/admin/restaurants")
    @admin_required
    def list_restaurants():
        restaurants = Restaurant.query.order_by(Restaurant.active.desc(), Restaurant.name.asc()).all()
        return render_template("restaurants.html", restaurants=restaurants)

    @app.route("/admin/restaurants/new", methods=["GET", "POST"])
    @admin_required
    def create_restaurant():
        if request.method == "POST":
            if not request.form.get("name", "").strip() or not request.form.get("city", "").strip() or not request.form.get("category", "").strip():
                flash("Restaurant name, city, and category are required.", "error")
                return render_template("restaurant_form.html", restaurant=None)

            name = request.form.get("name", "").strip()
            if Restaurant.query.filter(func.lower(Restaurant.name) == name.lower()).first():
                flash("A restaurant with that name already exists.", "error")
                return render_template("restaurant_form.html", restaurant=None)

            db.session.add(
                Restaurant(
                    name=name,
                    city=request.form.get("city", "").strip(),
                    category=request.form.get("category", "").strip(),
                    active=request.form.get("active") == "on",
                )
            )
            db.session.commit()
            flash("Restaurant created.", "success")
            return redirect(url_for("list_restaurants"))

        return render_template("restaurant_form.html", restaurant=None)

    @app.route("/admin/restaurants/<int:restaurant_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_restaurant(restaurant_id):
        restaurant = Restaurant.query.get_or_404(restaurant_id)
        if request.method == "POST":
            if not request.form.get("name", "").strip() or not request.form.get("city", "").strip() or not request.form.get("category", "").strip():
                flash("Restaurant name, city, and category are required.", "error")
                return render_template("restaurant_form.html", restaurant=restaurant)

            name = request.form.get("name", "").strip()
            existing = Restaurant.query.filter(func.lower(Restaurant.name) == name.lower(), Restaurant.id != restaurant.id).first()
            if existing:
                flash("A restaurant with that name already exists.", "error")
                return render_template("restaurant_form.html", restaurant=restaurant)

            restaurant.name = name
            restaurant.city = request.form.get("city", "").strip()
            restaurant.category = request.form.get("category", "").strip()
            restaurant.active = request.form.get("active") == "on"
            db.session.commit()
            flash("Restaurant updated.", "success")
            return redirect(url_for("list_restaurants"))

        return render_template("restaurant_form.html", restaurant=restaurant)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
