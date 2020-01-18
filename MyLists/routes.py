import json
import os
import platform
import secrets
import sys
import urllib
import requests
import time
import atexit
import dateutil

from PIL import Image
from flask_mail import Message
from MyLists.admin_views import User
from MyLists.API_data import API_data
from sqlalchemy import func, text, or_
from datetime import datetime, tzinfo, timedelta
from MyLists import app, db, bcrypt, mail, config
from flask_login import login_user, current_user, logout_user, login_required
from flask import render_template, url_for, flash, redirect, request, jsonify, session, abort
from MyLists.forms import RegistrationForm, LoginForm, UpdateAccountForm, ChangePasswordForm, AddFollowForm, \
    ResetPasswordForm, ResetPasswordRequestForm
from MyLists.models import Series, SeriesList, SeriesEpisodesPerSeason, Status, ListType, SeriesGenre, SeriesNetwork, \
    Follow, Anime, AnimeList, AnimeEpisodesPerSeason, AnimeGenre, AnimeNetwork, HomePage, Movies, MoviesGenre, \
    MoviesList, MoviesProd, MoviesActors, SeriesActors, AnimeActors, UserLastUpdate, Badges, MoviesCollections


config.read('config.ini')
try:
    themoviedb_api_key = config['TheMovieDB']['api_key']
except:
    print("Config file error. Please read the README to configure the config.ini file properly. Exit.")
    sys.exit()

class simple_utc(tzinfo):
    def tzname(self, **kwargs):
        return "UTC"
    def utcoffset(self, dt):
        return timedelta(0)


@app.before_first_request
def create_user():
    db.create_all()
    if User.query.filter_by(id='1').first() is None:
        admin = User(username='admin',
                     email='admin@admin.com',
                     password=bcrypt.generate_password_hash("password").decode('utf-8'),
                     image_file='default.jpg',
                     active=True,
                     private=True,
                     registered_on=datetime.utcnow(),
                     activated_on=datetime.utcnow())
        db.session.add(admin)
        add_badges_to_db()
    refresh_db_badges()
    db.session.commit()


################################################### Anonymous routes ###################################################


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def not_found(e):
    image_error = url_for('static', filename='img/error.jpg')
    return render_template('error.html', error_code=e, title='Error page', image_error=image_error), e


@app.route("/", methods=['GET', 'POST'])
def home():
    login_form = LoginForm()
    register_form = RegistrationForm()

    if login_form.validate_on_submit():
        user = User.query.filter_by(username=login_form.login_username.data).first()
        if user and not user.active:
            app.logger.info('[{}] Connexion attempt while account not activated'.format(user.id))
            flash('Your Account is not activated. Please check your e-mail address to activate your account.', 'danger')
        elif user and bcrypt.check_password_hash(user.password, login_form.login_password.data):
            login_user(user, remember=login_form.login_remember.data)
            app.logger.info('[{}] Logged in'.format(user.id))
            flash("You're now logged in. Welcome {0}".format(user.username), "success")
            next_page = request.args.get('next')
            if next_page is None:
                if user.homepage == HomePage.MYSERIESLIST:
                    return redirect(url_for('mymedialist', media_list='serieslist', user_name=current_user.username))
                elif user.homepage == HomePage.MYANIMELIST:
                    return redirect(url_for('mymedialist', media_list='animelist', user_name=current_user.username))
                elif user.homepage == HomePage.MYMOVIESLIST:
                    return redirect(url_for('mymedialist', media_list='movieslist', user_name=current_user.username))
                elif user.homepage == HomePage.ACCOUNT:
                    return redirect(url_for('account', user_name=current_user.username))
                elif user.homepage == HomePage.HALL_OF_FAME:
                    return redirect(url_for('hall_of_fame'))
                else:
                    abort(404)
            else:
                return redirect(next_page)
        else:
            flash('Login Failed. Please check Username and Password', 'warning')
    if register_form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(register_form.register_password.data).decode('utf-8')
        user = User(username=register_form.register_username.data,
                    email=register_form.register_email.data,
                    password=hashed_password,
                    registered_on=datetime.utcnow())
        db.session.add(user)
        db.session.commit()
        app.logger.info('[{}] New account registration : username = {}, email = {}'
                        .format(user.id, register_form.register_username.data, register_form.register_email.data))
        if send_register_email(user):
            flash('Your account has been created. Check your e-mail address to activate your account!', 'info')
            return redirect(url_for('home'))
        else:
            app.logger.error('[SYSTEM] Error while sending the registration email to {}'.format(user.email))
            abort(500)
    if current_user.is_authenticated:
        user = User.query.filter_by(id=current_user.id).first()
        if user.homepage == HomePage.MYSERIESLIST:
            return redirect(url_for('mymedialist', media_list='serieslist', user_name=current_user.username))
        elif user.homepage == HomePage.MYANIMELIST:
            return redirect(url_for('mymedialist', media_list='animelist', user_name=current_user.username))
        elif user.homepage == HomePage.MYMOVIESLIST:
            return redirect(url_for('mymedialist', media_list='movieslist', user_name=current_user.username))
        elif user.homepage == HomePage.ACCOUNT:
            return redirect(url_for('account', user_name=current_user.username))
        elif user.homepage == HomePage.HALL_OF_FAME:
            return redirect(url_for('hall_of_fame'))

    home_header = url_for('static', filename='img/home_header.jpg')
    home_img_1 = url_for('static', filename='img/home_img1.jpg')
    home_img_2 = url_for('static', filename='img/home_img2.jpg')
    return render_template('home.html',
                           login_form    = login_form,
                           register_form = register_form,
                           image_header  = home_header,
                           home_img_1    = home_img_1,
                           home_img_2    = home_img_2)


@app.route("/reset_password", methods=['GET', 'POST'])
def reset_password():
    form = ResetPasswordRequestForm()

    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if send_reset_email(user):
            app.logger.info('[{}] Reset password email sent'.format(user.id))
            flash('An email has been sent with instructions to reset your password.', 'info')
            return redirect(url_for('home'))
        else:
            app.logger.error('[SYSTEM] Error while sending the reset password email to {}'.format(user.email))
            flash("There was an error while sending the reset password email. Please try again later.")
            return redirect(url_for('home'))

    return render_template('reset_password.html', title='Reset Password', form=form)


@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_passord_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('reset_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user.password = hashed_password
        db.session.commit()
        app.logger.info('[{}] Password reset via reset password email'.format(user.id))
        flash('Your password has been updated! You are now able to log in', 'success')
        return redirect(url_for('home'))

    return render_template('reset_passord_token.html', title='Reset Password', form=form)


@app.route("/register_account/<token>", methods=['GET'])
def register_account_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    user = User.verify_reset_token(token)
    if user is None or user.active:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('reset_password'))

    user.active = True
    user.activated_on = datetime.utcnow()
    db.session.commit()
    app.logger.info('[{}] Account activated'.format(user.id))
    flash('Your account has been activated.', 'success')

    return redirect(url_for('home'))


################################################# Authenticated routes #################################################


@app.route("/admin", methods=['GET', 'POST'])
@login_required
def admin():
    pass


@app.route("/logout", methods=['GET'])
@login_required
def logout():
    user = User.query.filter_by(id=current_user.id).first()
    logout_user()
    app.logger.info('[{}] Logged out'.format(user.id))

    return redirect(url_for('home'))


@app.route('/account/<user_name>', methods=['GET', 'POST'])
@login_required
def account(user_name):
    user = User.query.filter_by(username=user_name).first()

    # Add forms
    follow_form = AddFollowForm()
    settings_form = UpdateAccountForm()
    password_form = ChangePasswordForm()

    # No account with this username and protection of the admin account
    if (user is None) or (user.id == 1 and current_user.id != 1):
        abort(404)

    # Check if the account is private or in the follow list
    follow = Follow.query.filter_by(user_id=current_user.id, follow_id=user.id).first()
    if current_user.id == user.id or current_user.id == 1:
        pass
    elif (user.private) and (follow is None):
        abort(404)

    # Follows form
    if follow_form.submit_follow.data and follow_form.validate():
        add_follow(follow_form.follow_to_add.data)
        return redirect(url_for('account', user_name=user_name, message='follows'))

    # Account settings form
    if settings_form.submit_account.data and settings_form.validate():
        if settings_form.biography.data:
            user.biography = settings_form.biography.data
            db.session.commit()
            app.logger.info('[{}] Settings updated: Biography updated'.format(user.id))
        elif settings_form.biography.data == "":
            user.biography = None
            db.session.commit()
            app.logger.info('[{}] Settings updated: Biography updated'.format(user.id))
        if settings_form.picture.data:
            picture_file = save_profile_picture(settings_form.picture.data)
            old_picture_file = user.image_file
            user.image_file = picture_file
            db.session.commit()
            app.logger.info('[{}] Settings updated: old picture file = {}, new picture file = {}'
                            .format(user.id, old_picture_file, user.image_file))
        if settings_form.username.data != user.username:
            old_username = user.username
            user.username = settings_form.username.data
            db.session.commit()
            app.logger.info('[{}] Settings updated: old username = {}, new username = {}'
                            .format(user.id, old_username, user.username))
        if settings_form.isprivate.data != user.private:
            old_value = user.private
            user.private = settings_form.isprivate.data
            db.session.commit()
            app.logger.info('[{}] Settings updated: old private mode = {}, new private mode = {}'
                            .format(user.id, old_value, settings_form.isprivate.data))

        old_value = user.homepage
        if settings_form.homepage.data == "msl":
            user.homepage = HomePage.MYSERIESLIST
        elif settings_form.homepage.data == "mml":
            user.homepage = HomePage.MYMOVIESLIST
        elif settings_form.homepage.data == "mal":
            user.homepage = HomePage.MYANIMELIST
        elif settings_form.homepage.data == "acc":
            user.homepage = HomePage.ACCOUNT
        elif settings_form.homepage.data == "hof":
            user.homepage = HomePage.HALL_OF_FAME

        db.session.commit()
        app.logger.info('[{}] Settings updated: old homepage = {}, new homepage = {}'
                        .format(user.id, old_value, settings_form.homepage.data))

        email_changed = False
        if settings_form.email.data != user.email:
            old_email = user.email
            user.transition_email = settings_form.email.data
            db.session.commit()
            app.logger.info('[{}] Settings updated : old email = {}, new email = {}'
                            .format(user.id, old_email, user.transition_email))
            email_changed = True
            if send_email_update_email(user):
                success = True
            else:
                success = False
                app.logger.error('[SYSTEM] Error while sending the email update email to {}'.format(user.email))
        if not email_changed:
            flash("Your account has been updated! ", 'success')
        else:
            if success:
                flash("Your account has been updated! Please click on the link to validate your new email address.",
                      'success')
            else:
                flash("There was an error internal error. Please contact the administrator.", 'danger')
        return redirect(url_for('account', user_name=current_user.username, message="settings"))
    elif request.method == 'GET':
        settings_form.biography.data = current_user.biography
        settings_form.username.data = current_user.username
        settings_form.email.data = current_user.email
        settings_form.isprivate.data = current_user.private

        if current_user.homepage == HomePage.MYSERIESLIST:
            settings_form.homepage.data = "msl"
        elif current_user.homepage == HomePage.MYMOVIESLIST:
            settings_form.homepage.data = "mml"
        elif current_user.homepage == HomePage.MYANIMELIST:
            settings_form.homepage.data = "mal"
        elif current_user.homepage == HomePage.ACCOUNT:
            settings_form.homepage.data = "acc"
        elif current_user.homepage == HomePage.HALL_OF_FAME:
            settings_form.homepage.data = "hof"

    # Password change form
    if password_form.submit_password.data and password_form.validate():
        hashed_password = bcrypt.generate_password_hash(password_form.confirm_new_password.data).decode('utf-8')
        current_user.password = hashed_password
        db.session.commit()
        app.logger.info('[{}] Password updated'.format(current_user.id))
        flash('Your password has been successfully updated!', 'success')
        return redirect(url_for('account', user_name=current_user.username, message="settings"))

    # Recover the follows list
    follows_list = db.session.query(User, Follow).join(Follow, Follow.follow_id == User.id)\
        .filter(Follow.user_id == user.id).group_by(Follow.follow_id).order_by(User.username).all()

    follows_list_data = []
    for follow in follows_list:
        picture_url = url_for('static', filename='profile_pics/{}'.format(follow[0].image_file))
        follow_data = {"username": follow[0].username,
                       "user_id" : follow[0].id,
                       "picture" : picture_url}

        if follow[0].private:
            test_private = Follow.query.filter_by(user_id=current_user.id, follow_id=follow[0].id).first()
            if (test_private is not None) or (current_user.id == 1):
                follows_list_data.append(follow_data)
            elif current_user.id == follow[0].id:
                follows_list_data.append(follow_data)
        else:
            follows_list_data.append(follow_data)

    # Recover the number of user that follows you
    followers = Follow.query.filter_by(follow_id=user.id).all()

    # Recover account data
    account_data = get_account_data(user, user_name, follows_list_data)

    # Recover the last updates of your follows for the follow TAB
    last_updates = get_follows_full_last_update(user.id)

    # Recover the last updates of the follows for the overview TAB
    if user.id == current_user.id:
        overview_updates = get_follows_last_update(user.id)
    else:
        overview_updates = get_user_last_update(user.id)

    # Recover the view count of the account and the media lists
    if current_user.id != 1 and user.id != current_user.id:
        user.profile_views = user.profile_views + 1
        profile_view_count = user.profile_views
        db.session.commit()
    else:
        profile_view_count = user.profile_views
    view_count = {"profile" : profile_view_count,
                  "series"  : user.series_views,
                  "anime"   : user.anime_views,
                  "movies"  : user.movies_views}

    # Recover the registered date
    registered_date = user.registered_on.strftime("%d %b %Y")

    # Reload on the specified form TAB
    message_tab = request.args.get("message")
    if message_tab is None:
        message_tab = 'overview'

    return render_template('account.html',
                           title            = "{}'s account".format(user.username),
                           data             = account_data,
                           joined           = registered_date,
                           view_count       = view_count,
                           user_id          = str(user.id),
                           user_name        = user_name,
                           message_tab      = message_tab,
                           follow_form      = follow_form,
                           followers        = len(followers),
                           last_updates     = last_updates,
                           overview_updates = overview_updates,
                           settings_form    = settings_form,
                           password_form    = password_form,
                           user_biography   = user.biography,
                           badges_unlocked  = "")


@app.route("/badges/<user_name>", methods=['GET', 'POST'])
@login_required
def badges(user_name):
    user = User.query.filter_by(username=user_name).first()

    # No account with this username and protection of the admin account
    if user is None or user.id == 1 and current_user.id != 1:
        abort(404)

    # Check if the account is private or in the follow list
    follow = Follow.query.filter_by(user_id=current_user.id, follow_id=user.id).first()
    if current_user.id == user.id or current_user.id == 1:
        pass
    elif user.private and follow is None:
        abort(404)

    badges = get_badges(user.id)[0]
    return render_template('badges.html',
                           title       = "{}'s badges".format(user_name),
                           user_badges = badges)


@app.route("/level_grade_data", methods=['GET'])
@login_required
def level_grade_data():
    all_ranks_list = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\levels_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/levels_ranks.csv")
    with open(path, "r") as fp:
        for line in fp:
            all_ranks_list.append(line.split(";"))

    all_ranks_list.pop(0)

    i, low, incr = [0, 0, 0]
    data = []
    while True:
        rank = all_ranks_list[i][2]
        if rank == 'ReachRank49':
            data.append(["ReachRank49", "Inheritor", [147, "+"], [(20*low)*(1+low), "+"],
                         [int(((20*low)*(1+low))/60), "+"]])
            break
        for j in range(i, len(all_ranks_list)):
            if str(rank) == all_ranks_list[j][2]:
                incr += 1
            else:
                data.append([rank, all_ranks_list[j-1][3], [low, incr-1],
                             [(20*low)*(1+low), ((20*incr)*(1+incr))-1],
                             [int(((20*low)*(1+low))/60), int((((20*incr)*(1+incr))-1)/60)]])
                i = j
                low = incr
                break

    return render_template('level_grade_data.html', title='Level grade data', data=data)


@app.route("/knowledge_grade_data", methods=['GET'])
@login_required
def knowledge_grade_data():
    all_knowledge_ranks_list = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\knowledge_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/knowledge_ranks.csv")
    with open(path, "r") as fp:
        for line in fp:
            all_knowledge_ranks_list.append(line.split(";"))

    i, low, incr = [1, 1, 1]
    data = []
    while True:
        rank = all_knowledge_ranks_list[i][1]
        if i == 346:
            data.append(["Knowledge_Emperor_Grade_4", "Knowledge Emperor Grade 4", [345, "+"]])
            break
        for j in range(i, len(all_knowledge_ranks_list)):
            if str(rank) == all_knowledge_ranks_list[j][1]:
                incr += 1
            else:
                data.append([rank, all_knowledge_ranks_list[j - 1][2], [low-1, incr-2]])
                i = j
                low = incr
                break

    return render_template('knowledge_grade_data.html', title='Knowledge grade data', data=data)


@app.route("/email_update/<token>", methods=['GET'])
@login_required
def email_update_token(token):
    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('home'))

    if str(user.id) != current_user.id:
        return redirect(url_for('home'))

    old_email = user.email
    user.email = user.transition_email
    user.transition_email = None
    db.session.commit()
    app.logger.info('[{}] Email successfully changed from {} to {}'.format(user.id, old_email, user.email))
    flash('Email successfully updated!', 'success')

    return redirect(url_for('home'))


@app.route("/hall_of_fame", methods=['GET'])
@login_required
def hall_of_fame():
    users = User.query.filter(User.id >= "2").filter_by(active=True).order_by(User.username.asc()).all()

    current_user_follows = Follow.query.filter_by(user_id=current_user.id).all()
    follows_list = []
    for follow in current_user_follows:
        follows_list.append(follow.follow_id)

    all_users_data = []
    for user in users:
        user_data = {}
        user_data["username"]        = user.username
        user_data["id"]              = user.id
        user_data["profile_picture"] = user.image_file

        series_level = get_level_and_grade(user.time_spent_series)
        user_data["series_level"]       = series_level["level"]
        user_data["series_percent"]     = series_level["level_percent"]
        user_data["series_grade_id"]    = series_level["grade_id"]
        user_data["series_grade_title"] = series_level["grade_title"]

        anime_level = get_level_and_grade(user.time_spent_anime)
        user_data["anime_level"]        = anime_level["level"]
        user_data["anime_percent"]      = anime_level["level_percent"]
        user_data["anime_grade_id"]     = anime_level["grade_id"]
        user_data["anime_grade_title"]  = anime_level["grade_title"]

        movies_level = get_level_and_grade(user.time_spent_movies)
        user_data["movies_level"]       = movies_level["level"]
        user_data["movies_percent"]     = movies_level["level_percent"]
        user_data["movies_grade_id"]    = movies_level["grade_id"]
        user_data["movies_grade_title"] = movies_level["grade_title"]

        knowledge_level = int(series_level["level"] + anime_level["level"] + movies_level["level"])
        knowledge_grade = get_knowledge_grade(knowledge_level)
        user_data["knowledge_level"]        = knowledge_level
        user_data["knowledge_grade_id"]     = knowledge_grade["grade_id"]
        user_data["knowledge_grade_title"]  = knowledge_grade["grade_title"]

        if user.id in follows_list:
            user_data["isfollowing"] = True
        else:
            user_data["isfollowing"] = False

        if user.id == current_user.id:
            user_data["isprivate"] = False
            user_data["iscurrentuser"] = True
        else:
            user_data["isprivate"] = user.private
            user_data["iscurrentuser"] = False

        all_users_data.append(user_data)

    return render_template("hall_of_fame.html", title='Hall of Fame', all_data=all_users_data)


@app.route("/global_stats", methods=['GET'])
@login_required
def global_stats():
    # Total time spent for each media
    times_spent = db.session.query(User, func.sum(User.time_spent_series), func.sum(User.time_spent_anime),
                             func.sum(User.time_spent_movies)).filter(User.id >= '2', User.active==True).all()

    if times_spent[0][0] is None:
        total_time = {"total": 0, "series": 0, "anime": 0, "movies": 0}
    else:
        total_time = {"total": int((times_spent[0][1]/60)+(times_spent[0][2]/60)+(times_spent[0][3]/60)),
                      "series": int(times_spent[0][1]/60),
                      "anime": int(times_spent[0][2]/60),
                      "movies": int(times_spent[0][3]/60)}

    # Top media in users' lists
    top_series = db.session.query(Series, SeriesList, func.count(SeriesList.series_id==Series.id).label("count"))\
        .join(SeriesList, SeriesList.series_id == Series.id).group_by(SeriesList.series_id)\
        .filter(SeriesList.user_id >= '2').order_by(text("count desc")).limit(5).all()
    top_anime = db.session.query(Anime, AnimeList, func.count(AnimeList.anime_id==Anime.id).label("count"))\
        .join(AnimeList, AnimeList.anime_id == Anime.id).group_by(AnimeList.anime_id)\
        .filter(AnimeList.user_id >= '2').order_by(text("count desc")).limit(5).all()
    top_movies = db.session.query(Movies, MoviesList, func.count(MoviesList.movies_id==Movies.id).label("count"))\
        .join(MoviesList, MoviesList.movies_id == Movies.id).group_by(MoviesList.movies_id)\
        .filter(MoviesList.user_id >= '2').order_by(text("count desc")).limit(5).all()

    top_all_series, top_all_anime, top_all_movies = [], [], []
    for i in range(5):
        try:
            tmp_series = {"name": top_series[i][0].name, "quantity": top_series[i][2]}
        except:
            tmp_series = {"name": "-", "quantity": "-"}
        try:
            tmp_anime = {"name": top_anime[i][0].name, "quantity": top_anime[i][2]}
        except:
            tmp_anime = {"name": "-", "quantity": "-"}
        try:
            tmp_movies = {"name": top_movies[i][0].name, "quantity": top_movies[i][2]}
        except:
            tmp_movies = {"name": "-", "quantity": "-"}

        top_all_series.append(tmp_series)
        top_all_anime.append(tmp_anime)
        top_all_movies.append(tmp_movies)

    most_present_media = {"series": top_all_series,
                          "anime": top_all_anime,
                          "movies": top_all_movies}

    # Top genre in users' lists
    series_genres = db.session.query(SeriesList, SeriesGenre, func.count(SeriesGenre.genre).label('count'))\
        .join(SeriesGenre, SeriesGenre.series_id == SeriesList.series_id)\
        .group_by(SeriesGenre.genre).filter(SeriesList.user_id >= '2').order_by(text('count desc')).limit(5).all()
    anime_genres = db.session.query(AnimeList, AnimeGenre, func.count(AnimeGenre.genre).label('count'))\
        .join(AnimeGenre, AnimeGenre.anime_id == AnimeList.anime_id)\
        .group_by(AnimeGenre.genre).filter(AnimeList.user_id >= '2').order_by(text('count desc')).limit(5).all()
    movies_genres = db.session.query(MoviesList, MoviesGenre, func.count(MoviesGenre.genre).label('count'))\
        .join(MoviesGenre, MoviesGenre.movies_id == MoviesList.movies_id)\
        .group_by(MoviesGenre.genre).filter(MoviesList.user_id >= '2').order_by(text('count desc')).limit(5).all()

    all_series_genres, all_anime_genres, all_movies_genres = [], [], []
    for i in range(5):
        try:
            tmp_series = {"genre": series_genres[i][1].genre, "quantity": series_genres[i][2]}
        except:
            tmp_series = {"genre": "-", "quantity": "-"}
        try:
            tmp_anime = {"genre": anime_genres[i][1].genre, "quantity": anime_genres[i][2]}
        except:
            tmp_anime = {"genre": "-", "quantity": "-"}
        try:
            tmp_movies = {"genre": movies_genres[i][1].genre, "quantity": movies_genres[i][2]}
        except:
            tmp_movies = {"genre": "-", "quantity": "-"}

        all_series_genres.append(tmp_series)
        all_anime_genres.append(tmp_anime)
        all_movies_genres.append(tmp_movies)

    most_genres_media = {"series": all_series_genres,
                         "anime": all_anime_genres,
                         "movies": all_movies_genres}

    # Top actors in the users' lists
    series_actors = db.session.query(SeriesList, SeriesActors, func.count(SeriesActors.name).label('count'))\
        .join(SeriesActors, SeriesActors.series_id == SeriesList.series_id)\
        .filter(SeriesActors.name != "Unknown").group_by(SeriesActors.name).filter(SeriesList.user_id >= '2')\
        .order_by(text('count desc')).limit(5).all()
    anime_actors = db.session.query(AnimeList, AnimeActors, func.count(AnimeActors.name).label('count'))\
        .join(AnimeActors, AnimeActors.anime_id == AnimeList.anime_id)\
        .filter(AnimeActors.name != "Unknown").group_by(AnimeActors.name).filter(AnimeList.user_id >= '2')\
        .order_by(text('count desc')).limit(5).all()
    movies_actors = db.session.query(MoviesList, MoviesActors, func.count(MoviesActors.name).label('count'))\
        .join(MoviesActors, MoviesActors.movies_id == MoviesList.movies_id)\
        .filter(MoviesActors.name != "Unknown").group_by(MoviesActors.name).filter(MoviesList.user_id >= '2')\
        .order_by(text('count desc')).limit(5).all()

    all_series_actors, all_anime_actors, all_movies_actors = [], [], []
    for i in range(5):
        try:
            tmp_series = {"name": series_actors[i][1].name, "quantity": series_actors[i][2]}
        except:
            tmp_series = {"name": "-", "quantity": "-"}
        try:
            tmp_anime = {"name": anime_actors[i][1].name, "quantity": anime_actors[i][2]}
        except:
            tmp_anime = {"name": "-", "quantity": "-"}
        try:
            tmp_movies = {"name": movies_actors[i][1].name, "quantity": movies_actors[i][2]}
        except:
            tmp_movies = {"name": "-", "quantity": "-"}

        all_series_actors.append(tmp_series)
        all_anime_actors.append(tmp_anime)
        all_movies_actors.append(tmp_movies)

    most_actors_media = {"series": all_series_actors,
                         "anime": all_anime_actors,
                         "movies": all_movies_actors}

    # Top dropped media in the users' lists
    series_dropped = db.session.query(Series, SeriesList, func.count(SeriesList.series_id==Series.id).label('count'))\
        .join(SeriesList, SeriesList.series_id == Series.id).filter_by(status=Status.DROPPED)\
        .group_by(SeriesList.series_id).filter(SeriesList.user_id >= '2').order_by(text('count desc')).limit(5).all()
    anime_dropped = db.session.query(Anime, AnimeList, func.count(AnimeList.anime_id==Anime.id).label('count'))\
        .join(AnimeList, AnimeList.anime_id == Anime.id).filter_by(status=Status.DROPPED).group_by(AnimeList.anime_id)\
        .filter(AnimeList.user_id >= '2').order_by(text('count desc')).limit(5).all()

    top_series_dropped, top_anime_dropped = [], []
    for i in range(5):
        try:
            tmp_series = {"name": series_dropped[i][0].name, "quantity": series_dropped[i][2]}
        except:
            tmp_series = {"name": "-", "quantity": "-"}
        try:
            tmp_anime = {"name": anime_dropped[i][0].name, "quantity": anime_dropped[i][2]}
        except:
            tmp_anime = {"name": "-", "quantity": "-"}

        top_series_dropped.append(tmp_series)
        top_anime_dropped.append(tmp_anime)

    top_dropped_media = {"series": top_series_dropped,
                         "anime": top_anime_dropped}

    # Total number of seasons/episodes watched for the series and anime
    total_series_eps_seasons = db.session.query(SeriesList, SeriesEpisodesPerSeason,
        func.group_concat(SeriesEpisodesPerSeason.episodes))\
        .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id==SeriesList.series_id)\
        .group_by(SeriesList.id).filter(SeriesList.user_id >= '2').all()
    total_anime_eps_seasons = db.session.query(AnimeList, AnimeEpisodesPerSeason,
        func.group_concat(AnimeEpisodesPerSeason.episodes))\
        .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == AnimeList.anime_id)\
        .group_by(AnimeList.id).filter(AnimeList.user_id >= '2').all()

    total_series_seas_watched = 0
    total_series_eps_watched = 0
    for element in total_series_eps_seasons:
        if element[0].status != Status.PLAN_TO_WATCH:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            if episodes[int(element[0].current_season) - 1] == int(element[0].last_episode_watched):
                total_series_seas_watched += int(element[0].current_season)
            else:
                total_series_seas_watched += int(element[0].current_season) - 1
            for i in range(1, element[0].current_season):
                total_series_eps_watched += episodes[i - 1]
            total_series_eps_watched += element[0].last_episode_watched

    total_anime_seas_watched = 0
    total_anime_eps_watched = 0
    for element in total_anime_eps_seasons:
        if element[0].status != Status.PLAN_TO_WATCH:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            if episodes[int(element[0].current_season) - 1] == int(element[0].last_episode_watched):
                total_anime_seas_watched += int(element[0].current_season)
            else:
                total_anime_seas_watched += int(element[0].current_season) - 1
            for i in range(1, element[0].current_season):
                total_anime_eps_watched += episodes[i - 1]
            total_anime_eps_watched += element[0].last_episode_watched

    total_seasons_media = {"series": total_series_seas_watched,
                           "anime": total_anime_seas_watched}
    total_episodes_media = {"series": total_series_eps_watched,
                            "anime": total_anime_eps_watched}

    return render_template("global_stats.html",
                           title='Global Stats',
                           total_time=total_time,
                           most_present_media=most_present_media,
                           most_actors_media=most_actors_media,
                           top_dropped_media=top_dropped_media,
                           total_seasons_media=total_seasons_media,
                           total_episodes_media=total_episodes_media,
                           most_genres_media=most_genres_media)


@app.route("/current_trends", methods=['GET'])
@login_required
def current_trends():
    # Recover the trending media data from the API
    trending_data = API_data(API_key=themoviedb_api_key).get_trending_media()

    if trending_data is None:
        flash('The current trends are not available right now, please try again later', 'warning')
        return redirect(url_for('account', user_name=current_user.username))

    series_trends = get_trending_data(trending_data[0], ListType.SERIES)
    anime_trends  = get_trending_data(trending_data[1], ListType.ANIME)
    movies_trends = get_trending_data(trending_data[2], ListType.MOVIES)

    return render_template("current_trends.html",
                           title="Current trends",
                           series_trends=series_trends,
                           anime_trends=anime_trends,
                           movies_trends=movies_trends)


@app.route("/movies_collection", methods=['GET'])
@login_required
def movies_collection():
    collection_movie = db.session.query(Movies, MoviesList, MoviesCollections) \
        .join(MoviesList, MoviesList.movies_id == Movies.id) \
        .join(MoviesCollections, MoviesCollections.collection_id == Movies.collection_id) \
        .filter(Movies.collection_id != None, MoviesList.user_id == current_user.id)\
        .group_by(Movies.id).all()

    completed_collections = []
    ongoing_collections = []
    for movie in collection_movie:
        movie_data = {}
        movie_data["name"] = movie[2].name
        movie_data["total"] = movie[2].parts
        movie_data["parts"] = movie[3]
        movie_data["overview"] = movie[2].overview
        movie_data["poster"] = '/static/covers/movies_collection_covers/' + movie[2].poster
        if movie_data["total"] == movie_data["parts"]:
            movie_data["completed"] = True
            completed_collections.append(movie_data)
        else:
            movie_data["completed"] = False
            ongoing_collections.append(movie_data)

    completed_collections.sort(key=lambda x: (x['parts']), reverse=True)
    ongoing_collections.sort(key=lambda x: (x['total']), reverse=True)

    return render_template('movies_collection.html',
                           title='Movies collection',
                           completed_collections=completed_collections,
                           ongoing_collections=ongoing_collections,
                           length_completed=len(completed_collections),
                           length_ongoing=len(ongoing_collections))


@app.route("/follow_status", methods=['POST'])
@login_required
def follow_status():
    try:
        json_data = request.get_json()
        follow_id = int(json_data['follow_id'])
        status = json_data['follow_status']
    except:
        abort(400)

    # Check if the follow ID exist in the User database and status is boolean
    if User.query.filter_by(id=follow_id).first() is None or type(status) is not bool:
        abort(400)

    # Check the status
    if status:
        # Check if the follow already exists
        if Follow.query.filter_by(user_id=current_user.id, follow_id=follow_id).first() is not None:
            abort(400)

        # Follow the user
        new_follow = Follow(user_id=current_user.id, follow_id=follow_id)
        db.session.add(new_follow)
        db.session.commit()
        app.logger.info('[{}] follow the user with ID {}'.format(current_user.id, follow_id))
    else:
        # Check if the user to unfollow is in the follow list
        if Follow.query.filter_by(user_id=current_user.id, follow_id=follow_id).first() is None:
            abort(400)

        # Unfollow the user
        Follow.query.filter_by(user_id=current_user.id, follow_id=follow_id).delete()
        db.session.commit()
        app.logger.info('[{}] Follow with ID {} unfollowed'.format(current_user.id, follow_id))

    return '', 204


#################################################### Media routes ######################################################


@app.route("/<media_list>/<user_name>", methods=['GET'])
@login_required
def mymedialist(media_list, user_name):
    user = User.query.filter_by(username=user_name).first()

    list_type = check_list_type(media_list)
    if list_type is None:
        abort(404)

    # Check if the user exists
    if user is None:
        abort(404)

    # Check if the current user can see the target user's list
    if current_user.id != user.id and current_user.id != 1:
        follow = Follow.query.filter_by(user_id=current_user.id, follow_id=user.id).first()
        if user.id == 1:
            abort(404)
        if user.private:
            if follow is None:
                abort(404)

    # Check the route and retrieve the media data
    if list_type == ListType.SERIES:
        element_data = db.session.query(Series, SeriesList, func.group_concat(SeriesGenre.genre.distinct()),
                                        func.group_concat(SeriesNetwork.network.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.season.distinct()),
                                        func.group_concat(SeriesActors.name.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(SeriesList, SeriesList.series_id == Series.id)\
            .join(SeriesGenre, SeriesGenre.series_id == Series.id)\
            .join(SeriesNetwork, SeriesNetwork.series_id == Series.id)\
            .join(SeriesActors, SeriesActors.series_id == Series.id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == Series.id)\
            .filter(SeriesList.user_id == user.id).group_by(Series.id).order_by(Series.name.asc()).all()
        covers_path = url_for('static', filename='covers/series_covers/')
        media_all_data = get_medialist_data(element_data, ListType.SERIES, covers_path, user.id)
    elif list_type == ListType.ANIME:
        element_data = db.session.query(Anime, AnimeList, func.group_concat(AnimeGenre.genre.distinct()),
                                        func.group_concat(AnimeNetwork.network.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.season.distinct()),
                                        func.group_concat(AnimeActors.name.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(AnimeList, AnimeList.anime_id == Anime.id)\
            .join(AnimeGenre, AnimeGenre.anime_id == Anime.id)\
            .join(AnimeNetwork, AnimeNetwork.anime_id == Anime.id)\
            .join(AnimeActors, AnimeActors.anime_id == Anime.id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == Anime.id)\
            .filter(AnimeList.user_id == user.id).group_by(Anime.id).order_by(Anime.name.asc()).all()
        covers_path = url_for('static', filename='covers/anime_covers/')
        media_all_data = get_medialist_data(element_data, ListType.ANIME, covers_path, user.id)
    elif list_type == ListType.MOVIES:
        element_data = db.session.query(Movies, MoviesList, func.group_concat(MoviesGenre.genre.distinct()),
                                        func.group_concat(MoviesProd.production_company.distinct()),
                                        func.group_concat(MoviesActors.name.distinct()))\
            .join(MoviesList, MoviesList.movies_id == Movies.id)\
            .join(MoviesGenre, MoviesGenre.movies_id == Movies.id)\
            .join(MoviesProd, MoviesProd.movies_id == Movies.id)\
            .join(MoviesActors, MoviesActors.movies_id == Movies.id)\
            .filter(MoviesList.user_id == user.id).group_by(Movies.id).order_by(Movies.name.asc()).all()
        covers_path = url_for('static', filename='covers/movies_covers/')
        media_all_data = get_medialist_data(element_data, ListType.MOVIES, covers_path, user.id)

    # View count of the media lists
    if current_user.id != 1 and user.id != current_user.id:
        if media_list == ListType.SERIES:
            user.series_views = user.series_views + 1
        elif media_list == ListType.ANIME:
            user.anime_views = user.anime_views + 1
        elif media_list == ListType.MOVIES:
            user.movies_views = user.movies_views + 1
        db.session.commit()

    if list_type != ListType.MOVIES:
        return render_template('mymedialist/series_anime_list.html',
                               title            = "{}'s {}".format(user_name, media_list),
                               all_data         = media_all_data["all_data"],
                               common_elements  = media_all_data["common_elements"],
                               media_list       = media_list,
                               target_user_name = user_name,
                               target_user_id   = str(user.id))
    elif list_type == ListType.MOVIES:
        return render_template('mymedialist/movieslist.html',
                               title            = "{}'s {}".format(user_name, media_list),
                               all_data         = media_all_data["all_data"],
                               common_elements  = media_all_data["common_elements"],
                               media_list       = media_list,
                               target_user_name = user_name,
                               target_user_id   = str(user.id))


@app.route('/update_element_season', methods=['POST'])
@login_required
def update_element_season():
    try:
        json_data  = request.get_json()
        new_season = int(json_data['season'])+1
        element_id = int(json_data['element_id'])
        element_type  = json_data['element_type']
    except:
        abort(400)

    list_type = check_list_type(element_type)
    if list_type is None:
        abort(400)

    if list_type == ListType.ANIME:
        # Check if the element exists
        anime = Anime.query.filter_by(id=element_id).first()
        if anime is None:
            abort(400)

        # Check if the element is in the current user's list
        anime_list = AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first()
        if anime_list is None:
            abort(400)

        # Check if the season number is between 1 and <last_season>
        all_seasons = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id)\
            .order_by(AnimeEpisodesPerSeason.season).all()
        if (1 > new_season > all_seasons[-1].season):
            abort(400)

        # Set the new data and the last update
        old_season = anime_list.current_season
        old_episode = anime_list.last_episode_watched
        anime_list.current_season = new_season
        anime_list.last_episode_watched = 1
        app.logger.info("[{}] Anime season with ID {} updated: {}".format(current_user.id, element_id, new_season))
        set_last_update(media_name=anime.name, media_type=ListType.ANIME, old_season=old_season,
                        new_season=anime_list.current_season, old_episode=old_episode, new_episode=1)

        # Commit the changes
        db.session.commit()
    elif list_type == ListType.SERIES:
        # Check if the element exists
        series = Series.query.filter_by(id=element_id).first()
        if series is None:
            abort(400)

        # Check if the element is in the current user's list
        series_list = SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).first()
        if series_list is None:
            abort(400)

        # Check if the season number is between 1 and <last_season>
        all_seasons = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id)\
            .order_by(SeriesEpisodesPerSeason.season).all()
        if (1 > new_season > all_seasons[-1].season):
            abort(400)

        # Set the new data and the last update
        old_season = series_list.current_season
        old_episode = series_list.last_episode_watched
        series_list.current_season = new_season
        series_list.last_episode_watched = 1
        app.logger.info('[{}] Series season with ID {} updated: {}'.format(current_user.id, element_id, new_season))
        set_last_update(media_name=series.name, media_type=ListType.SERIES, old_season=old_season,
                        new_season=series_list.current_season, old_episode=old_episode, new_episode=1)

        # Commit the changes
        db.session.commit()

    # Compute total time spent
    if list_type == ListType.ANIME:
        compute_time_spent(type="season", old_eps=old_episode, new_eps=None, old_seas=old_season, new_seas=new_season,
                           all_seas_data=all_seasons, media=anime, list_type=ListType.ANIME)
    elif list_type == ListType.SERIES:
        compute_time_spent(type="season", old_eps=old_episode, new_eps=None, old_seas=old_season, new_seas=new_season,
                           all_seas_data=all_seasons, media=series, list_type=ListType.SERIES)

    return '', 204


@app.route('/update_element_episode', methods=['POST'])
@login_required
def update_element_episode():
    try:
        json_data = request.get_json()
        new_episode = int(json_data['episode'])+1
        element_id = int(json_data['element_id'])
        element_type = json_data['element_type']
    except:
        abort(400)

    list_type = check_list_type(element_type)
    if list_type is None:
        abort(400)

    if list_type == ListType.ANIME:
        # Check if the element exists
        anime = Anime.query.filter_by(id=element_id).first()
        if anime is None:
            abort(400)

        # Check if the element is in the current user's list
        anime_list = AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first()
        if anime_list is None:
            abort(400)

        # Check if the episode number is between 1 and <last_episode>
        last_episode = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id, season=anime_list.current_season) \
            .first().episodes
        if (1 > new_episode > last_episode):
            abort(400)

        # Set the new data and the last update
        old_season = anime_list.current_season
        old_episode = anime_list.last_episode_watched
        anime_list.last_episode_watched = new_episode
        app.logger.info('[{}] Anime episode with ID {} updated: {}'.format(current_user.id, element_id, new_episode))
        set_last_update(media_name=anime.name, media_type=ListType.ANIME, old_season=old_season, new_season=old_season,
                        old_episode=old_episode, new_episode=new_episode)

        # Commit the changes
        db.session.commit()
    elif list_type == ListType.SERIES:
        # Check if the element exists
        series = Series.query.filter_by(id=element_id).first()
        if series is None:
            abort(400)

        # Check if the element is in the current user's list
        series_list = SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).first()
        if series_list is None:
            abort(400)

        # Check if the episode number is between 1 and <last_episode>
        last_episode = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id, season=series_list.current_season)\
            .first().episodes
        if (1 > new_episode > last_episode):
            abort(400)

        # Set the new data and last update
        old_season = series_list.current_season
        old_episode = series_list.last_episode_watched
        series_list.last_episode_watched = new_episode
        db.session.commit()
        app.logger.info('[{}] Series episode with ID {} updated: {}'.format(current_user.id, element_id, new_episode))
        set_last_update(media_name=series.name, media_type=ListType.SERIES, old_season=old_season,
                        new_season=old_season, old_episode=old_episode, new_episode=new_episode)

        # Commit the changes
        db.session.commit()

    # Compute total time spent
    if list_type == ListType.ANIME:
        compute_time_spent(type='episode', new_eps=new_episode, old_eps=old_episode, media=anime,
                           list_type=ListType.ANIME)
    elif list_type == ListType.SERIES:
        compute_time_spent(type='episode', new_eps=new_episode, old_eps=old_episode, media=series,
                           list_type=ListType.SERIES)

    return '', 204


@app.route('/delete_element', methods=['POST'])
@login_required
def delete_element():
    try:
        json_data = request.get_json()
        element_id = int(json_data['delete'])
        element_type = json_data['element_type']
    except:
        abort(400)

    list_type = check_list_type(element_type)
    if list_type is None:
        abort(400)

    if list_type == ListType.SERIES:
        # Check if series exists in the database
        series = Series.query.filter_by(id=element_id).first()
        if series is None:
            abort(400)

        # Check if series exists in list of the current user
        series_list = SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).first()
        if series_list is None:
            abort(400)
    elif list_type == ListType.ANIME:
        # Check if anime exists in the database
        anime = Anime.query.filter_by(id=element_id).first()
        if anime is None:
            abort(400)

        # Check if anime exists in list of the current user
        anime_list = AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first()
        if anime_list is None:
            abort(400)
    elif list_type == ListType.MOVIES:
        # Check if movie exists in the database
        movies = Movies.query.filter_by(id=element_id).first()
        if movies is None:
            abort(400)

        # Check if movie exists in the user's list
        movies_list = MoviesList.query.filter_by(user_id=current_user.id, movies_id=element_id).first()
        if movies_list is None:
            abort(400)

    # Compute total time spent
    if list_type == ListType.SERIES:
        all_series_seasons = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id)\
            .order_by(SeriesEpisodesPerSeason.season).all()
        compute_time_spent(type="delete", old_eps=series_list.last_episode_watched, old_seas=series_list.current_season,
                           all_seas_data=all_series_seasons, media=series, list_type=list_type)
    elif list_type == ListType.ANIME:
        all_anime_seasons = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id)\
            .order_by(AnimeEpisodesPerSeason.season).all()
        compute_time_spent(type="delete", old_eps=anime_list.last_episode_watched, old_seas=anime_list.current_season,
                           all_seas_data=all_anime_seasons, media=anime, list_type=list_type)
    elif list_type == ListType.MOVIES:
        compute_time_spent(type="delete", media=movies, list_type=list_type)

    # Delete the media from the user' list
    if list_type == ListType.SERIES:
        SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).delete()
        db.session.commit()
        app.logger.info('[{}] Series with ID {} deleted'.format(current_user.id, element_id))
    elif list_type == ListType.ANIME:
        AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).delete()
        db.session.commit()
        app.logger.info('[{}] Anime with ID {} deleted'.format(current_user.id, element_id))
    elif list_type == ListType.MOVIES:
        MoviesList.query.filter_by(user_id=current_user.id, movies_id=element_id).delete()
        db.session.commit()
        app.logger.info('[{}] Movie with ID {} deleted'.format(current_user.id, element_id))

    return '', 204


@app.route('/change_element_category', methods=['POST'])
@login_required
def change_element_category():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        element_new_category = json_data['status']
        element_id = int(json_data['element_id'])
        element_type = json_data['element_type']
    except:
        abort(400)

    list_type = check_list_type(element_type)
    if list_type is None:
        abort(400)

    new_status = check_cat_type(list_type, element_new_category)
    if new_status is None:
        abort(400)

    # Check if the element is in the user's list
    if list_type == ListType.SERIES:
        element = SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).first()
    elif list_type == ListType.ANIME:
        element = AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first()
    elif list_type == ListType.MOVIES:
        element = MoviesList.query.filter_by(user_id=current_user.id, movies_id=element_id).first()
    if element is None:
        abort(400)

    old_status = element.status
    element.status = new_status

    if new_status == Status.COMPLETED:
        # Set to the last seasons and episodes
        if list_type == ListType.SERIES:
            seasons_and_eps = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id) \
                .order_by(SeriesEpisodesPerSeason.season).all()
            element.current_season = len(seasons_and_eps)
            element.last_episode_watched = seasons_and_eps[-1].episodes
        elif list_type == ListType.ANIME:
            seasons_and_eps = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id) \
                .order_by(AnimeEpisodesPerSeason.season).all()
            element.current_season = len(seasons_and_eps)
            element.last_episode_watched = seasons_and_eps[-1].episodes
    elif new_status == Status.RANDOM:
        # Set to first season and episode
        element.current_season = 1
        element.last_episode_watched = 1
    elif new_status == Status.PLAN_TO_WATCH:
        # Set to first season and episode
        if list_type != ListType.MOVIES:
            element.current_season = 1
            element.last_episode_watched = 1

    db.session.commit()
    app.logger.info('[{}] Category of the element with ID {} ({}) changed to {}'
                    .format(current_user.id, element_id, list_type, new_status))

    # Compute total time spent and set last update
    if list_type == ListType.SERIES:
        series = Series.query.filter_by(id=element_id).first()
        set_last_update(media_name=series.name, media_type=list_type, old_status=old_status, new_status=new_status)
        compute_time_spent(type="category", old_eps=element.last_episode_watched, old_seas=element.current_season,
                           media=series, old_status=old_status, new_status=new_status,
                           list_type=list_type)
    elif list_type == ListType.ANIME:
        anime = Anime.query.filter_by(id=element_id).first()
        set_last_update(media_name=anime.name, media_type=list_type, old_status=old_status, new_status=new_status)
        compute_time_spent(type="category", old_eps=element.last_episode_watched, old_seas=element.current_season,
                           media=anime, old_status=old_status, new_status=new_status,
                           list_type=list_type)
    elif list_type == ListType.MOVIES:
        movie = Movies.query.filter_by(id=element_id).first()
        set_last_update(media_name=movie.name, media_type=list_type, old_status=old_status, new_status=new_status)
        compute_time_spent(type="category", old_eps=element.last_episode_watched, old_seas=element.current_season,
                           media=movie, old_status=old_status, new_status=new_status,
                           list_type=list_type)

    return '', 204


@app.route('/add_element', methods=['POST'])
@login_required
def add_element():
    try:
        json_data = request.get_json()
        element_id = int(json_data['element_id'])
        element_type = json_data['element_type']
        element_cat = json_data['element_cat']
        from_other_list = json_data['from_other_list']
    except:
        abort(400)

    list_type = check_list_type(element_type)
    if list_type is None:
        abort(400)

    new_status = check_cat_type(list_type, element_cat)
    if new_status is None:
        abort(400)

    if from_other_list is True:
        kargs = {'id': element_id}
    elif from_other_list is False:
        kargs = {'themoviedb_id': element_id}
    else:
        abort(400)

    # Check if the element ID exist in the database
    if list_type == ListType.SERIES:
        element = Series.query.filter_by(**kargs).first()
    elif list_type == ListType.ANIME:
        element = Anime.query.filter_by(**kargs).first()
    elif list_type == ListType.MOVIES:
        element = Movies.query.filter_by(**kargs).first()

    # If media ID exists, add to user without API calls
    if element is not None:
        # Check if the element is already in the current's user list
        if list_type == ListType.SERIES:
            if SeriesList.query.filter_by(user_id=current_user.id, series_id=element.id).first():
                flash("This series is already in your list", "warning")
        elif list_type == ListType.ANIME:
            if AnimeList.query.filter_by(user_id=current_user.id, anime_id=element.id).first():
                flash("This anime is already in your list", "warning")
        elif list_type == ListType.MOVIES:
            if MoviesList.query.filter_by(user_id=current_user.id, movies_id=element.id).first():
                flash("This movie is already in your list", "warning")
        add_element_to_user(element.id, current_user.id, list_type, new_status)
    else:
        add_element_in_base(element_id, list_type, new_status)

    return '', 204


@app.route('/autocomplete/<media>', methods=['GET'])
@login_required
def autocomplete(media):
    list_type = check_list_type(media)
    if list_type is None:
        abort(400)

    search = request.args.get('q')

    if list_type == ListType.SERIES:
        results = API_data(API_key=themoviedb_api_key).autocomplete_search(search, list_type)
    elif list_type == ListType.ANIME:
        results = API_data(API_key=themoviedb_api_key).autocomplete_search(search, list_type)
    elif list_type == ListType.MOVIES:
        results = API_data(API_key=themoviedb_api_key).autocomplete_search(search, list_type)

    return jsonify(matching_results=results)


###################################################### Functions #######################################################


def check_list_type(list_type):
    if list_type == 'serieslist':
        return ListType.SERIES
    elif list_type == 'animelist':
        return ListType.ANIME
    elif list_type == 'movieslist':
        return ListType.MOVIES
    else:
        return None


def check_cat_type(list_type, status):
    if list_type != ListType.MOVIES:
        if status == 'Watching':
            return Status.WATCHING
        elif status == 'Completed':
            return Status.COMPLETED
        elif status == 'On Hold':
            return Status.ON_HOLD
        elif status == 'Random':
            return Status.RANDOM
        elif status == 'Dropped':
            return Status.DROPPED
        elif status == 'Plan to Watch':
            return Status.PLAN_TO_WATCH
        else:
            return None
    elif list_type == ListType.MOVIES:
        if status == 'Completed':
            return Status.COMPLETED
        elif status == 'Plan to Watch':
            return Status.PLAN_TO_WATCH
        else:
            return None


def compute_time_spent(type=None, old_eps=None, new_eps=None, old_seas=None, new_seas=None,
                       all_seas_data=None, media=None, old_status=None, new_status=None, list_type=None):

    def eps_watched_seasons(old_season, old_episode, new_season, all_seasons):
        nb_eps_watched = 0
        if new_season - old_season > 0:
            for i in range(old_season, new_season):
                nb_eps_watched += all_seasons[i-1].episodes
            nb_eps_watched -= old_episode + 1
        else:
            for i in range(new_season, old_season):
                nb_eps_watched -= all_seasons[i-1].episodes
            nb_eps_watched -= old_episode - 1
        return nb_eps_watched

    def eps_watched_delete(season, episode, all_seasons):
        nb_eps_watched = 0
        for i in range(1, season):
            nb_eps_watched += all_seasons[i-1].episodes
        nb_eps_watched += episode
        return nb_eps_watched

    def eps_watched_completed():
        pass

    def eps_watched_ptw_random():
        pass

    if type == 'episode':
        if list_type == ListType.ANIME:
            old_time = current_user.time_spent_anime
            current_user.time_spent_anime = old_time + (new_eps - old_eps) * media.episode_duration

        elif list_type == ListType.SERIES:
            old_time = current_user.time_spent_series
            current_user.time_spent_series = old_time + (new_eps - old_eps) * media.episode_duration

    elif type == 'season':
        eps_watched = eps_watched_seasons(old_seas, old_eps, new_seas, all_seas_data)

        if list_type == ListType.ANIME:
            old_time = current_user.time_spent_anime
            current_user.time_spent_anime = old_time + (eps_watched * media.episode_duration)

        elif list_type == ListType.SERIES:
            old_time = current_user.time_spent_series
            current_user.time_spent_series = old_time + (eps_watched * media.episode_duration)

    elif type == 'delete':
        if list_type == ListType.ANIME:
            eps_watched = eps_watched_delete(old_seas, old_eps, all_seas_data)
            old_time = current_user.time_spent_anime
            current_user.time_spent_anime = old_time - (eps_watched * media.episode_duration)

        elif list_type == ListType.SERIES:
            eps_watched = eps_watched_delete(old_seas, old_eps, all_seas_data)
            old_time = current_user.time_spent_series
            current_user.time_spent_series = old_time - (eps_watched * media.episode_duration)

        elif list_type == ListType.MOVIES:
            old_time = current_user.time_spent_movies
            current_user.time_spent_movies = old_time - media.runtime

    elif type == 'category':
        if new_status == 'Watching' or new_status == 'On Hold' or new_status == 'Dropped':
            if list_type == ListType.ANIME:
                if old_status == Status.RANDOM or old_status == Status.PLAN_TO_WATCH:
                    current_user.time_spent_anime = current_user.time_spent_anime + media.episode_duration
            elif list_type == ListType.SERIES:
                if old_status == Status.RANDOM or old_status == Status.PLAN_TO_WATCH:
                    current_user.time_spent_series = current_user.time_spent_series + media.episode_duration

        elif new_status == 'Completed' or new_status == 'Completed Animation':
            if list_type == ListType.ANIME:
                if old_status == Status.RANDOM or old_status == Status.PLAN_TO_WATCH:
                    current_user.time_spent_anime = current_user.time_spent_anime + \
                                                    (media.total_episodes*media.episode_duration)
                else:
                    eps_watched = eps_watched_completed()
                    current_user.time_spent_anime = current_user.time_spent_anime + eps_watched*media.episode_duration
            elif list_type == ListType.SERIES:
                if old_status == Status.RANDOM or old_status == Status.PLAN_TO_WATCH:
                    current_user.time_spent_series = current_user.time_spent_series + \
                                                    (media.total_episodes*media.episode_duration)
                else:
                    eps_watched = eps_watched_completed()
                    current_user.time_spent_series = current_user.time_spent_series + eps_watched*media.episode_duration
            elif list_type == ListType.MOVIES:
                current_user.time_spent_movies = current_user.time_spent_movies + media.runtime

        elif new_status == 'Random':
            if list_type == ListType.ANIME:
                if old_status != Status.PLAN_TO_WATCH:
                    eps_watched = eps_watched_ptw_random()
                    current_user.time_spent_anime = current_user.time_spent_anime - eps_watched*media.episode_duration
            elif list_type == ListType.SERIES:
                if old_status != Status.PLAN_TO_WATCH:
                    eps_watched = eps_watched_ptw_random()
                    current_user.time_spent_series = current_user.time_spent_series - eps_watched*media.episode_duration

        elif new_status == 'Plan to Watch':
            if list_type == ListType.ANIME:
                if old_status != Status.RANDOM:
                    eps_watched = eps_watched_ptw_random()
                    current_user.time_spent_anime = current_user.time_spent_anime - eps_watched*media.episode_duration
            elif list_type == ListType.SERIES:
                if old_status != Status.RANDOM:
                    eps_watched = eps_watched_ptw_random()
                    current_user.time_spent_series = current_user.time_spent_series - eps_watched*media.episode_duration
            elif list_type == ListType.MOViES:
                current_user.time_spent_movies = current_user.time_spent_movies - media.runtime

    db.session.commit()


def compute_media_time_spent(list_type):
    user = User.query.filter_by(id=current_user.id).first()

    if list_type == ListType.ANIME:
        element_data = db.session.query(AnimeList, Anime, func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(Anime, Anime.id == AnimeList.anime_id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == AnimeList.anime_id)\
            .filter(AnimeList.user_id == current_user.id).group_by(AnimeList.anime_id)
    elif list_type == ListType.SERIES:
        element_data = db.session.query(SeriesList, Series, func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(Series, Series.id == SeriesList.series_id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == SeriesList.series_id)\
            .filter(SeriesList.user_id == current_user.id).group_by(SeriesList.series_id)
    elif list_type == ListType.MOVIES:
        element_data = db.session.query(MoviesList, Movies).join(Movies, Movies.id == MoviesList.movies_id)\
            .filter(MoviesList.user_id == current_user.id).group_by(MoviesList.movies_id)

    if list_type == ListType.ANIME or list_type == ListType.SERIES:
        total_time = 0
        for element in element_data:
            if element[0].status == Status.COMPLETED:
                try:
                    total_time += element[1].episode_duration * element[1].total_episodes
                except:
                    pass
            elif element[0].status != Status.PLAN_TO_WATCH:
                try:
                    episodes = element[2].split(",")
                    episodes = [int(x) for x in episodes]
                    for i in range(1, element[0].current_season):
                        total_time += element[1].episode_duration * episodes[i - 1]
                    total_time += element[0].last_episode_watched * element[1].episode_duration
                except:
                    pass
    elif list_type == ListType.MOVIES:
        total_time = 0
        for element in element_data:
            if element[0].status == Status.COMPLETED or element[0].status == Status.COMPLETED_ANIMATION:
                try:
                    total_time += element[1].runtime
                except:
                    pass

    if list_type == ListType.ANIME:
        user.time_spent_anime = total_time
    elif list_type == ListType.SERIES:
        user.time_spent_series = total_time
    elif list_type == ListType.MOVIES:
        user.time_spent_movies = total_time

    db.session.commit()


def get_trending_data(trends_data, list_type):
    trending_list = []
    tmdb_posters_path = "http://image.tmdb.org/t/p/w300"
    i = 0
    if list_type == ListType.SERIES:
        for data in trends_data.get("results"):
            series = {}
            series["title"] = data.get("name", "Unknown")
            series["poster_path"] = tmdb_posters_path + data.get("poster_path")
            if series["poster_path"] is None or data.get("poster_path") == "":
                series["poster_path"] = "static/covers/movies_covers/default.jpg"
            series["first_air_date"] = data.get("first_air_date", "Unknown")
            if series["first_air_date"] != "Unknown":
                series["first_air_date"] = datetime.strptime(series["first_air_date"], '%Y-%m-%d').strftime("%d %b %Y")
            series["overview"] = data.get("overview", "There is no overview for this series.")
            series["tmdb_link"] = "https://www.themoviedb.org/tv/{}".format(data.get("id"))
            trending_list.append(series)
            i += 1
            if i > 11:
                break

        return trending_list
    elif list_type == ListType.ANIME:
        for data in trends_data.get("top"):
            anime = {}
            anime["title"] = data.get("title", "Unknown")
            anime["poster_path"] = data.get("image_url")
            if anime["poster_path"] is None or data.get("image_url") == "":
                anime["poster_path"] = "static/covers/anime_covers/default.jpg"
            anime["first_air_date"] = data.get("start_date")
            anime["overview"] = "There is no overview from this API. " \
                                "You can check it on MyAnimeList by clicking on the title"
            anime["tmdb_link"] = data.get("url")
            trending_list.append(anime)
            i += 1
            if i > 11:
                break

        return trending_list
    elif list_type == ListType.MOVIES:
        for data in trends_data.get("results"):
            movies = {}
            movies["title"] = data.get("title", "Unknown")
            movies["poster_path"] = tmdb_posters_path + data.get("poster_path")
            if movies["poster_path"] is None or data.get("poster_path") == "":
                movies["poster_path"] = "static/covers/movies_covers/default.jpg"
            movies["release_date"] = datetime.strptime(data.get("release_date"), '%Y-%m-%d').strftime("%d %b %Y")
            movies["overview"] = data.get("overview", "No overview available for this movie.")
            movies["tmdb_link"] = "https://www.themoviedb.org/movie/{}".format(data.get("id"))
            trending_list.append(movies)
            i += 1
            if i > 11:
                break

        return trending_list


def get_account_data(user, user_name, follows_list_data):
    account_data             = {}
    account_data["series"]   = {}
    account_data["movies"]   = {}
    account_data["anime"]    = {}
    account_data["id"]       = user.id
    account_data["username"] = user_name
    account_data["follows"]  = follows_list_data

    if user.id != current_user.id:
        if Follow.query.filter_by(user_id=current_user.id, follow_id=user.id).first() is None:
            account_data["isfollowing"] = False
        else:
            account_data["isfollowing"] = True

    # Recover the profile picture
    account_data["profile_picture"] = url_for('static', filename='profile_pics/{0}'.format(user.image_file))

    # Time spent in hours for all media
    account_data["series"]["time_spent_hour"] = round(user.time_spent_series/60)
    account_data["movies"]["time_spent_hour"] = round(user.time_spent_movies/60)
    account_data["anime"]["time_spent_hour"]  = round(user.time_spent_anime/60)

    # Time spent in days for all media
    account_data["series"]["time_spent_day"] = round(user.time_spent_series/1440, 2)
    account_data["movies"]["time_spent_day"] = round(user.time_spent_movies/1440, 2)
    account_data["anime"]["time_spent_day"]  = round(user.time_spent_anime/1440, 2)

    def get_list_count(user_id, list_type):
        if list_type is ListType.SERIES:
            media_count = db.session.query(SeriesList, func.count(SeriesList.status)) \
                .filter_by(user_id=user_id).group_by(SeriesList.status).all()
        if list_type is ListType.ANIME:
            media_count = db.session.query(AnimeList, func.count(AnimeList.status)) \
                .filter_by(user_id=user_id).group_by(AnimeList.status).all()
        if list_type is ListType.MOVIES:
            media_count = db.session.query(MoviesList, func.count(MoviesList.status)) \
                .filter_by(user_id=user_id).group_by(MoviesList.status).all()

        watching, completed, completed_animation, onhold, \
        random, dropped, plantowatch = [0 for _ in range(7)]
        for media in media_count:
            if media[0].status == Status.WATCHING:
                watching = media[1]
            if media[0].status == Status.COMPLETED:
                completed = media[1]
            if media[0].status == Status.COMPLETED_ANIMATION:
                completed_animation = media[1]
            if media[0].status == Status.ON_HOLD:
                onhold = media[1]
            if media[0].status == Status.RANDOM:
                random = media[1]
            if media[0].status == Status.DROPPED:
                dropped = media[1]
            if media[0].status == Status.PLAN_TO_WATCH:
                plantowatch = media[1]
        total = sum(tot[1] for tot in media_count)

        return {"watching": watching,
                "completed": completed,
                "completed_animation": completed_animation,
                "onhold": onhold,
                "random": random,
                "dropped": dropped,
                "plantowatch": plantowatch,
                "total": total - plantowatch}

    # Count media elements of each category
    series_count = get_list_count(user.id, ListType.SERIES)
    account_data["series"]["watching_count"]    = series_count["watching"]
    account_data["series"]["completed_count"]   = series_count["completed"]
    account_data["series"]["onhold_count"]      = series_count["onhold"]
    account_data["series"]["random_count"]      = series_count["random"]
    account_data["series"]["dropped_count"]     = series_count["dropped"]
    account_data["series"]["plantowatch_count"] = series_count["plantowatch"]
    account_data["series"]["total_count"]       = series_count["total"]

    anime_count = get_list_count(user.id, ListType.ANIME)
    account_data["anime"]["watching_count"]     = anime_count["watching"]
    account_data["anime"]["completed_count"]    = anime_count["completed"]
    account_data["anime"]["onhold_count"]       = anime_count["onhold"]
    account_data["anime"]["random_count"]       = anime_count["random"]
    account_data["anime"]["dropped_count"]      = anime_count["dropped"]
    account_data["anime"]["plantowatch_count"]  = anime_count["plantowatch"]
    account_data["anime"]["total_count"]        = anime_count["total"]

    movies_count = get_list_count(user.id, ListType.MOVIES)
    account_data["movies"]["completed_count"]           = movies_count["completed"]
    account_data["movies"]["completed_animation_count"] = movies_count["completed_animation"]
    account_data["movies"]["plantowatch_count"]         = movies_count["plantowatch"]
    account_data["movies"]["total_count"]               = movies_count["total"]

    # Count the total number of seen episodes for the series
    series_data = db.session.query(SeriesList, SeriesEpisodesPerSeason,
                                   func.group_concat(SeriesEpisodesPerSeason.episodes))\
        .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == SeriesList.series_id)\
        .filter(SeriesList.user_id == user.id).group_by(SeriesList.series_id).all()

    nb_eps_watched = 0
    for element in series_data:
        if element[0].status != Status.PLAN_TO_WATCH and element[0].status != Status.RANDOM:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            for i in range(1, element[0].current_season):
                nb_eps_watched += episodes[i-1]
            nb_eps_watched += element[0].last_episode_watched
    account_data["series"]["nb_ep_watched"] = nb_eps_watched

    # Count the total number of seen episodes for the anime
    anime_data = db.session.query(AnimeList, AnimeEpisodesPerSeason,
                                      func.group_concat(AnimeEpisodesPerSeason.episodes))\
        .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == AnimeList.anime_id)\
        .filter(AnimeList.user_id == user.id).group_by(AnimeList.anime_id)

    nb_eps_watched = 0
    for element in anime_data:
        if element[0].status != Status.PLAN_TO_WATCH and element[0].status != Status.RANDOM:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            for i in range(1, element[0].current_season):
                nb_eps_watched += episodes[i-1]
            nb_eps_watched += element[0].last_episode_watched
    account_data["anime"]["nb_ep_watched"] = nb_eps_watched

    # Media percentages
    if account_data["series"]["nb_ep_watched"] == 0:
        account_data["series"]["element_percentage"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    else:
        account_data["series"]["element_percentage"] = [
            (float(account_data["series"]["watching_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["completed_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["onhold_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["random_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["dropped_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["plantowatch_count"]/account_data["series"]["total_count"]))*100]
    if account_data["anime"]["nb_ep_watched"] == 0:
        account_data["anime"]["element_percentage"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    else:
        account_data["anime"]["element_percentage"] = [
            (float(account_data["anime"]["watching_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["completed_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["onhold_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["random_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["dropped_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["plantowatch_count"]/account_data["anime"]["total_count"]))*100]
    if account_data["movies"]["total_count"] == 0:
        account_data["movies"]["element_percentage"] = [0.0, 0.0, 0.0]
    else:
        account_data["movies"]["element_percentage"] = [
            (float(account_data["movies"]["completed_count"]/account_data["movies"]["total_count"]))*100,
            (float(account_data["movies"]["completed_animation_count"]/account_data["movies"]["total_count"]))*100,
            (float(account_data["movies"]["plantowatch_count"]/account_data["movies"]["total_count"]))*100]

    # Grades and levels for each media
    series_level = get_level_and_grade(user.time_spent_series)
    account_data["series_level"]       = series_level["level"]
    account_data["series_percent"]     = series_level["level_percent"]
    account_data["series_grade_id"]    = series_level["grade_id"]
    account_data["series_grade_title"] = series_level["grade_title"]

    anime_level = get_level_and_grade(user.time_spent_anime)
    account_data["anime_level"]       = anime_level["level"]
    account_data["anime_percent"]     = anime_level["level_percent"]
    account_data["anime_grade_id"]    = anime_level["grade_id"]
    account_data["anime_grade_title"] = anime_level["grade_title"]

    movies_level = get_level_and_grade(user.time_spent_movies)
    account_data["movies_level"]       = movies_level["level"]
    account_data["movies_percent"]     = movies_level["level_percent"]
    account_data["movies_grade_id"]    = movies_level["grade_id"]
    account_data["movies_grade_title"] = movies_level["grade_title"]

    knowledge_level = int(series_level["level"] + anime_level["level"] + movies_level["level"])
    knowledge_grade = get_knowledge_grade(knowledge_level)
    account_data["knowledge_level"]       = knowledge_level
    account_data["knowledge_grade_id"]    = knowledge_grade["grade_id"]
    account_data["knowledge_grade_title"] = knowledge_grade["grade_title"]

    return account_data


def get_level_and_grade(total_time_min):
    # Compute the corresponding level using the equation
    element_level_tmp = "{:.2f}".format(round((((400+80*(total_time_min))**(1/2))-20)/40, 2))
    element_level = element_level_tmp.split('.')
    element_level[0] = int(element_level[0])

    # Level and grade calculation
    list_all_levels_ranks = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\levels_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/levels_ranks.csv")
    with open(path, 'r') as fp:
        for line in fp:
            list_all_levels_ranks.append(line.split(";"))

    list_all_levels_ranks.pop(0)

    user_level_rank = []
    # Check if the user has a level greater than 125
    if element_level[0] > 125:
        user_level_rank.append(["General_Grade_4", "General Grade 4"])
    else:
        for rank in list_all_levels_ranks:
            if int(rank[0]) == element_level[0]:
                user_level_rank.append([str(rank[2]), str(rank[3])])

    return {"level": element_level[0],
            "level_percent": element_level[1],
            "grade_id": user_level_rank[0][0],
            "grade_title": user_level_rank[0][1]}


def get_knowledge_grade(knowledge_level):
    # Recover knowledge ranks
    list_all_knowledge_ranks = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\knowledge_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/knowledge_ranks.csv")
    with open(path, 'r') as fp:
        for line in fp:
            list_all_knowledge_ranks.append(line.split(";"))

    user_knowledge_rank = []
    # Check if the user has a level greater than 345
    if int(knowledge_level) > 345:
        user_knowledge_rank.append(["Knowledge_Emperor_Grade_4", "Knowledge Emperor Grade 4"])
    else:
        for rank in list_all_knowledge_ranks:
            if str(rank[0]) == str(knowledge_level):
                user_knowledge_rank.append([str(rank[1]), str(rank[2])])

    return {"grade_id": user_knowledge_rank[0][0], "grade_title": user_knowledge_rank[0][1]}


def get_badges(user_id):
    user = User.query.filter_by(id=user_id).first()

    def get_queries():
        series_data = db.session.query(Series, SeriesList, func.group_concat(SeriesGenre.genre.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.season.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(SeriesList, SeriesList.series_id == Series.id)\
            .join(SeriesGenre, SeriesGenre.series_id == Series.id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == Series.id)\
            .filter(SeriesList.user_id == user_id)\
            .filter(or_(SeriesGenre.genre == "Animation", SeriesGenre.genre == "Comedy", SeriesGenre.genre == "Crime",
                        SeriesGenre.genre == "Documentary", SeriesGenre.genre == "Mystery",
                        SeriesGenre.genre == "Historical", SeriesGenre.genre == "War & Politics",
                        SeriesGenre.genre == "Sci-Fi & Fantasy"))\
            .group_by(Series.id).all()

        anime_data = db.session.query(Anime, AnimeList, func.group_concat(AnimeGenre.genre.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.season.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(AnimeList, AnimeList.anime_id == Anime.id)\
            .join(AnimeGenre, AnimeGenre.anime_id == Anime.id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == Anime.id)\
            .filter(AnimeList.user_id == user_id) \
            .filter(or_(AnimeGenre.genre == "Comedy", AnimeGenre.genre == "Police", AnimeGenre.genre == "Supernatural",
                        AnimeGenre.genre == "Music", AnimeGenre.genre == "Mystery", AnimeGenre.genre == "Historical",
                        AnimeGenre.genre == "Romance", AnimeGenre.genre == "Sci-Fi", AnimeGenre.genre == "Fantasy",
                        AnimeGenre.genre == "Horror", AnimeGenre.genre == "Thriller", AnimeGenre.genre == "Sports",
                        AnimeGenre.genre == "Slice of Life", AnimeGenre.genre == "School")) \
            .group_by(Anime.id).all()

        movies_data = db.session.query(Movies, MoviesList, func.group_concat(MoviesGenre.genre.distinct()))\
            .join(MoviesList, MoviesList.movies_id == Movies.id)\
            .join(MoviesGenre, MoviesGenre.movies_id == Movies.id)\
            .filter(MoviesList.user_id == user_id) \
            .filter(or_(MoviesGenre.genre == "Comedy", MoviesGenre.genre == "Crime", MoviesGenre.genre == "Music",
                        MoviesGenre.genre == "Mystery", MoviesGenre.genre == "History",
                        MoviesGenre.genre == "Documentary", MoviesGenre.genre == "Romance",
                        MoviesGenre.genre == "Horror", MoviesGenre.genre == "War", MoviesGenre.genre == "Fantasy",
                        MoviesGenre.genre == "Thriller", MoviesGenre.genre == "Animation",
                        MoviesGenre.genre == "Science Fiction"))\
            .group_by(Movies.id).all()

        total_data = series_data + anime_data + movies_data

        return total_data

    def get_episodes_and_time(element):
        if element[1].status == Status.COMPLETED or element[1].status == Status.COMPLETED_ANIMATION:
            try:
                return [1, element[0].runtime]
            except:
                return [element[0].total_episodes, int(element[0].episode_duration) * element[0].total_episodes]
        elif element[1].status != Status.PLAN_TO_WATCH and element[1].status != Status.RANDOM:
            nb_season = len(element[3].split(","))
            nb_episodes = element[4].split(",")[:nb_season]

            ep_duration = int(element[0].episode_duration)
            ep_counter = 0
            for i in range(0, element[1].current_season - 1):
                ep_counter += int(nb_episodes[i])
            episodes_watched = ep_counter + element[1].last_episode_watched
            time_watched = (ep_duration * episodes_watched)
            return [episodes_watched, time_watched]
        else:
            return [0, 0]

    def create_badge_dict(badge, unlocked, time=None, count=None):
        if time is not None:
            value = int(time/60)
        else:
            value = count

        badge_data = {}
        badge_data["type"] = badge.type
        badge_data["image_id"] = badge.image_id
        badge_data["title"] = badge.title
        badge_data["unlocked"] = unlocked
        badge_data["value"] = value

        return badge_data

    total_data = get_queries()
    time_spent = int(user.time_spent_anime) + int(user.time_spent_series) + int(user.time_spent_movies)

    all_badges = []
    time_by_genre = {}
    time_classic = 0
    count_completed = 0
    long_media_shows = 0
    long_media_movies = 0
    for element in total_data:
        eps_and_time = get_episodes_and_time(element)
        episodes_watched = eps_and_time[0]
        time_watched = eps_and_time[1]

        # Genres badges
        genres = element[2].split(',')
        for genre in genres:
            if genre not in time_by_genre:
                if genre == "Supernatural":
                    if "Mystery" not in time_by_genre:
                        time_by_genre["Mystery"] = time_watched
                    else:
                        time_by_genre["Mystery"] += time_watched
                elif genre == "Police":
                    if "Crime" not in time_by_genre:
                        time_by_genre["Crime"] = time_watched
                    else:
                        time_by_genre["Crime"] += time_watched
                elif genre == "War" or genre == "War & Politics" or genre == "History":
                    if "Historical" not in time_by_genre:
                        time_by_genre["Historical"] = time_watched
                    else:
                        time_by_genre["Historical"] += time_watched
                elif genre == "Sci-Fi & Fantasy":
                    if "Fantasy" not in time_by_genre:
                        time_by_genre["Fantasy"] = time_watched
                    else:
                        time_by_genre["Fantasy"] += time_watched
                    if "Science Fiction" not in time_by_genre:
                        time_by_genre["Science Fiction"] = time_watched
                    else:
                        time_by_genre["Science Fiction"] += time_watched
                elif genre == "Sci-Fi":
                    if "Science Fiction" not in time_by_genre:
                        time_by_genre["Science Fiction"] = time_watched
                    else:
                        time_by_genre["Science Fiction"] += time_watched
                elif genre == "School":
                    if "Slice of Life" not in time_by_genre:
                        time_by_genre["Slice of Life"] = time_watched
                    else:
                        time_by_genre["Slice of Life"] += time_watched
                else:
                    time_by_genre[genre] = time_watched
            else:
                time_by_genre[genre] += time_watched

        # Classic media bagdes, before 1990 without movies
        try:
            first_year = int(element[0].first_air_date.split('-')[0])
            if first_year <= 1990 and element[1].status != Status.PLAN_TO_WATCH \
                    and element[1].status != Status.RANDOM:
                time_classic += time_watched
        except:
            pass
        # Classic media bagdes, before 1990 movies
        try:
            release_date = int(element[0].release_date.split('-')[0])
            if release_date <= 1990 and element[1].status != Status.PLAN_TO_WATCH:
                time_classic += time_watched
        except:
            pass

        # Completed media badges without movies
        try:
            status = element[0].status
            if (status=="Ended" or status=="Canceled" or status=="Released") \
                    and (element[1].status == Status.COMPLETED or element[1].status == Status.COMPLETED_ANIMATION):
                count_completed += 1
        except:
            pass
        # Completed media badges movies
        try:
            status = element[0].released
            if (status=="Released") and (element[1].status == Status.COMPLETED
                                         or element[1].status == Status.COMPLETED_ANIMATION):
                count_completed += 1
        except:
            pass

        # Long media shows, more than 100 episodes
        try:
            if int(episodes_watched) >= 100:
                long_media_shows += 1
        except:
            pass

        # Long media movies, more than 2h30
        try:
            if element[0].runtime >= 150:
                long_media_movies += 1
        except:
            pass

    # Genres badges
    genres_values = ["Mystery", "Historical", "Horror", "Music", "Romance", "Sports", "Slice of Life", "Comedy",
                     "Crime", "Documentary", "Science Fiction", "Animation", "Fantasy", "Thriller"]
    for i in range(0, len(genres_values)):
        badge = db.session.query(Badges).filter_by(title=genres_values[i]).first()
        try:
            genre_time_data = time_by_genre[genres_values[i]]
        except:
            genre_time_data = 0
        count_unlocked = int((genre_time_data/60)/badge.threshold)
        badge_data = create_badge_dict(badge, count_unlocked, time=genre_time_data)
        all_badges.append(badge_data)

    # Classic badges
    badge = db.session.query(Badges).filter_by(type="classic").first()
    count_unlocked = int((time_classic/60)/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, time=time_classic)
    all_badges.append(badge_data)

    # Completed badges
    badge = db.session.query(Badges).filter_by(type="completed").first()
    count_unlocked = int(count_completed/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, count=count_completed)
    all_badges.append(badge_data)

    # Time badges
    badge = db.session.query(Badges).filter_by(type="total-time").first()
    count_unlocked = int((time_spent/1440)/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, time=(time_spent/24))
    all_badges.append(badge_data)

    # Long shows badges
    badge = db.session.query(Badges).filter_by(type="longshows").first()
    count_unlocked = int(long_media_shows/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, count=long_media_shows)
    all_badges.append(badge_data)

    # Long movies badges
    badge = db.session.query(Badges).filter_by(type="longmovies").first()
    count_unlocked = int(long_media_movies/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, count=long_media_movies)
    all_badges.append(badge_data)

    all_badges.sort(key=lambda x: (x['unlocked'], x['value']), reverse=True)
    total_unlocked = 0
    for item in all_badges:
        total_unlocked += item["unlocked"]

    return [all_badges, total_unlocked]


def get_medialist_data(element_data, list_type, covers_path, user_id):
    if user_id != current_user.id:
        if list_type == ListType.ANIME:
            current_list = db.session.query(AnimeList.anime_id).filter_by(user_id=current_user.id).all()
        elif list_type == ListType.SERIES:
            current_list = db.session.query(SeriesList.series_id).filter_by(user_id=current_user.id).all()
        elif list_type == ListType.MOVIES:
            current_list = db.session.query(MoviesList.movies_id).filter_by(user_id=current_user.id).all()
        current_list = [r[0] for r in current_list]
    else:
        current_list = []

    if list_type != ListType.MOVIES:
        watching_list    = []
        completed_list   = []
        onhold_list      = []
        random_list      = []
        dropped_list     = []
        plantowatch_list = []

        common_elements = 0
        for element in element_data:
            # Get episodes per season
            nb_season = len(element[4].split(","))
            eps_per_season = element[6].split(",")[:nb_season]
            # change str to int
            eps_per_season = [int(i) for i in eps_per_season]

            # Change first air time format
            try:
                tmp_date = datetime.strptime(element[0].first_air_date, '%Y-%m-%d')
                first_air_date = tmp_date.strftime("%d %b %Y")
            except:
                first_air_date = "Unknown"

            # Change last air time format
            try:
                tmp_date = datetime.strptime(element[0].last_air_date, '%Y-%m-%d')
                last_air_date = tmp_date.strftime("%d %b %Y")
            except:
                last_air_date = "Unknown"

            # Get actors
            try:
                tmp = element[5]
                actors = tmp.replace(',', ', ')
            except:
                actors = "Unknown"

            # Get genres
            try:
                tmp = element[2]
                genres = tmp.replace(',', ', ')
            except:
                genres = "Unknown"

            # Get networks
            try:
                tmp = element[3]
                networks = tmp.replace(',', ', ')
            except:
                networks = "Unknown"

            element_info = {"id": element[0].id,
                            "cover": "{}{}".format(covers_path, element[0].image_cover),
                            "name": element[0].name,
                            "original_name": element[0].original_name,
                            "first_air_date": first_air_date,
                            "last_air_date": last_air_date,
                            "created_by": element[0].created_by,
                            "episode_duration": element[0].episode_duration,
                            "homepage": element[0].homepage,
                            "in_production": element[0].in_production,
                            "origin_country": element[0].origin_country,
                            "total_seasons": element[0].total_seasons,
                            "total_episodes": element[0].total_episodes,
                            "status": element[0].status,
                            "vote_average": element[0].vote_average,
                            "vote_count": element[0].vote_count,
                            "synopsis": element[0].synopsis,
                            "popularity": element[0].popularity,
                            "last_episode_watched": element[1].last_episode_watched,
                            "eps_per_season": eps_per_season,
                            "current_season": element[1].current_season,
                            "score": element[1].score,
                            "actors": actors,
                            "genres": genres,
                            "networks": networks}

            if element[1].status == Status.WATCHING:
                if element[0].id in current_list:
                    watching_list.append([element_info, True])
                    common_elements += 1
                else:
                    watching_list.append([element_info, False])
            elif element[1].status == Status.COMPLETED:
                if element[0].id in current_list:
                    completed_list.append([element_info, True])
                    common_elements += 1
                else:
                    completed_list.append([element_info, False])
            elif element[1].status == Status.ON_HOLD:
                if element[0].id in current_list:
                    onhold_list.append([element_info, True])
                    common_elements += 1
                else:
                    onhold_list.append([element_info, False])
            elif element[1].status == Status.RANDOM:
                if element[0].id in current_list:
                    random_list.append([element_info, True])
                    common_elements += 1
                else:
                    random_list.append([element_info, False])
            elif element[1].status == Status.DROPPED:
                if element[0].id in current_list:
                    dropped_list.append([element_info, True])
                    common_elements += 1
                else:
                    dropped_list.append([element_info, False])
            elif element[1].status == Status.PLAN_TO_WATCH:
                if element[0].id in current_list:
                    plantowatch_list.append([element_info, True])
                    common_elements += 1
                else:
                    plantowatch_list.append([element_info, False])

        element_all_data = [[watching_list, "WATCHING"], [completed_list, "COMPLETED"], [onhold_list, "ON HOLD"],
                            [random_list, "RANDOM"], [dropped_list, "DROPPED"], [plantowatch_list, "PLAN TO WATCH"]]

        try:
            percentage = int(common_elements/len(element_data)*100)
        except:
            percentage = 0
        all_data_media = {"all_data": element_all_data,
                          "common_elements": [common_elements, len(element_data), percentage]}

        return all_data_media
    elif list_type == ListType.MOVIES:
        completed_list           = []
        completed_list_animation = []
        plantowatch_list         = []

        common_elements = 0
        for element in element_data:
            # Change release date format
            try:
                tmp_date = datetime.strptime(element[0].release_date, '%Y-%m-%d')
                release_date = tmp_date.strftime("%d %b %Y")
            except:
                release_date = "Unknown"

            # Get actors
            try:
                tmp = element[4]
                actors = tmp.replace(',', ', ')
            except:
                actors = "Unknown"

            # Get genres
            try:
                tmp = element[2]
                genres = tmp.replace(',', ', ')
            except:
                genres = "Unknown"

            # Get production companies
            try:
                tmp = element[3]
                prod_companies = tmp.replace(',', ', ')
            except:
                prod_companies = "Unknown"

            element_info = {"id": element[0].id,
                            "cover": "{}{}".format(covers_path, element[0].image_cover),
                            "name": element[0].name,
                            "original_name": element[0].original_name,
                            "release_date": release_date,
                            "homepage": element[0].homepage,
                            "runtime": element[0].runtime,
                            "original_language": element[0].original_language,
                            "synopsis": element[0].synopsis,
                            "vote_average": element[0].vote_average,
                            "vote_count": element[0].vote_count,
                            "popularity": element[0].popularity,
                            "budget": element[0].budget,
                            "revenue": element[0].revenue,
                            "tagline": element[0].tagline,
                            "score": element[1].score,
                            "actors": actors,
                            "genres": genres,
                            "prod_companies": prod_companies}

            if element[1].status == Status.COMPLETED:
                if element[0].id in current_list:
                    completed_list.append([element_info, True])
                    common_elements += 1
                else:
                    completed_list.append([element_info, False])
            elif element[1].status == Status.COMPLETED_ANIMATION:
                if element[0].id in current_list:
                    completed_list_animation.append([element_info, True])
                    common_elements += 1
                else:
                    completed_list_animation.append([element_info, False])
            elif element[1].status == Status.PLAN_TO_WATCH:
                if element[0].id in current_list:
                    plantowatch_list.append([element_info, True])
                    common_elements += 1
                else:
                    plantowatch_list.append([element_info, False])

        element_all_data = [[completed_list, "COMPLETED"], [completed_list_animation, "COMPLETED ANIMATION"] ,
                            [plantowatch_list, "PLAN TO WATCH"]]

        try:
            percentage = int(common_elements/len(element_data)*100)
        except:
            percentage = 0
        all_data_media = {"all_data": element_all_data,
                          "common_elements": [common_elements, len(element_data), percentage]}

        return all_data_media


def set_last_update(media_name, media_type, old_status=None, new_status=None, old_season=None,
                    new_season=None, old_episode=None, new_episode=None):
    user = User.query.filter_by(id=current_user.id).first()
    element = UserLastUpdate.query.filter_by(user_id=user.id).all()
    # if len(element) >= 6:
    #     oldest_id = UserLastUpdate.query.filter_by(user_id=current_user.id)\
    #         .order_by(UserLastUpdate.date.asc()).first().id
    #     UserLastUpdate.query.filter_by(id=oldest_id).delete()
    #     db.session.commit()

    update = UserLastUpdate(user_id=user.id, media_name=media_name, media_type=media_type, old_status=old_status,
                            new_status=new_status, old_season=old_season, new_season=new_season,
                            old_episode=old_episode, new_episode=new_episode, date=datetime.utcnow())
    db.session.add(update)
    db.session.commit()


def get_follows_full_last_update(user_id):
    follows_update = db.session.query(Follow, User, UserLastUpdate)\
        .join(User, Follow.follow_id == User.id)\
        .join(UserLastUpdate, UserLastUpdate.user_id == Follow.follow_id)\
        .filter(Follow.user_id == user_id)\
        .order_by(User.username, UserLastUpdate.date.desc()).all()

    tmp = ""
    follows_data = []
    for i in range(0, len(follows_update)):
        element = follows_update[i]
        if element[1].username != tmp:
            tmp = element[1].username
            follow_data = {}
            follow_data["username"] = element[1].username
            follow_data["update"] = []

        element_data = {}
        # Season or episode update
        if element[2].old_status is None and element[2].new_status is None:
            element_data["update"] = ["S{:02d}.E{:02d}".format(element[2].old_season, element[2].old_episode),
                                      "S{:02d}.E{:02d}".format(element[2].new_season, element[2].new_episode)]

        # Category update
        elif element[2].old_status is not None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].old_status.value).replace("Animation", "Anime"),
                                      "{}".format(element[2].new_status.value).replace("Animation", "Anime")]

        # Media newly added
        elif element[2].old_status is None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].new_status.value)]

        element_data["date"] = element[2].date.replace(tzinfo=simple_utc()).isoformat()
        element_data["media_name"] = element[2].media_name

        if element[2].media_type == ListType.SERIES:
            element_data["category"] = "series"
        elif element[2].media_type == ListType.ANIME:
            element_data["category"] = "anime"
        elif element[2].media_type == ListType.MOVIES:
            element_data["category"] = "movie"

        # TODO: TEMP FIX
        if len(follow_data["update"]) <= 5:
            follow_data["update"].append(element_data)

        try:
            if element[1].username != follows_update[i+1][1].username:
                follows_data.append(follow_data)
            else:
                pass
        except:
            follows_data.append(follow_data)

    return follows_data


def get_user_last_update(user_id):
    last_update = UserLastUpdate.query.filter_by(user_id=user_id).order_by(UserLastUpdate.date.desc()).limit(4)
    update = []
    for element in last_update:
        element_data = {}
        # Season or episode update
        if element.old_status is None and element.new_status is None:
            element_data["update"] = ["S{:02d}.E{:02d}".format(element.old_season, element.old_episode),
                                      "S{:02d}.E{:02d}".format(element.new_season, element.new_episode)]

        # Category update
        elif element.old_status is not None and element.new_status is not None:
            element_data["update"] = ["{}".format(element.old_status.value).replace("Animation", "Anime"),
                                      "{}".format(element.new_status.value).replace("Animation", "Anime")]

        # Newly added media
        elif element.old_status is None and element.new_status is not None:
            element_data["update"] = ["{}".format(element.new_status.value)]

        # Update date
        element_data["date"] = element.date.replace(tzinfo=simple_utc()).isoformat()

        element_data["media_name"] = element.media_name

        if element.media_type == ListType.SERIES:
            element_data["category"] = "series"
        elif element.media_type == ListType.ANIME:
            element_data["category"] = "anime"
        elif element.media_type == ListType.MOVIES:
            element_data["category"] = "movie"

        update.append(element_data)

    return update


def get_follows_last_update(user_id):
    follows_update = db.session.query(Follow, User, UserLastUpdate)\
                               .join(User, Follow.follow_id == User.id)\
                               .join(UserLastUpdate, UserLastUpdate.user_id == Follow.follow_id)\
                               .filter(Follow.user_id == user_id)\
                               .order_by(UserLastUpdate.date.desc()).limit(4)

    update = []
    for element in follows_update:
        element_data = {}
        # Season or episode update
        if element[2].old_status is None and element[2].new_status is None:
            element_data["update"] = ["S{:02d}.E{:02d}".format(element[2].old_season, element[2].old_episode),
                                      "S{:02d}.E{:02d}".format(element[2].new_season, element[2].new_episode)]

        # Category update
        elif element[2].old_status is not None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].old_status.value).replace("Animation", "Anime"),
                                      "{}".format(element[2].new_status.value).replace("Animation", "Anime")]

        # Newly added media
        elif element[2].old_status is None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].new_status.value)]

        # Update date
        element_data["date"] = element[2].date.replace(tzinfo=simple_utc()).isoformat()

        element_data["media_name"] = element[2].media_name

        if element[2].media_type == ListType.SERIES:
            element_data["category"] = "series"
        elif element[2].media_type == ListType.ANIME:
            element_data["category"] = "anime"
        elif element[2].media_type == ListType.MOVIES:
            element_data["category"] = "movie"

        element_data["username"] = element[1].username

        update.append(element_data)

    return update


def add_element_to_user(element_id, user_id, list_type, status):
    if list_type == ListType.SERIES:
        # Set season/episode to max if the "completed" category is selected
        if status == Status.COMPLETED:
            seasons_eps = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id).all()
            user_list = SeriesList(user_id=user_id,
                                   series_id=element_id,
                                   current_season=len(seasons_eps),
                                   last_episode_watched=seasons_eps[-1].episodes,
                                   status=status)
        else:
            user_list = SeriesList(user_id=user_id,
                                   series_id=element_id,
                                   current_season=1,
                                   last_episode_watched=1,
                                   status=status)

        db.session.add(user_list)
        db.session.commit()
        app.logger.info('[{}] Added a series with the ID {}'.format(user_id, element_id))
        series = Series.query.filter_by(id=element_id).first()
        set_last_update(media_name=series.name, media_type=list_type, new_status=status)
    elif list_type == ListType.ANIME:
        # Set season/episode to max if the "completed" category is selected
        if status == Status.COMPLETED:
            seasons_eps = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id).all()
            user_list = AnimeList(user_id=user_id,
                                  anime_id=element_id,
                                  current_season=len(seasons_eps),
                                  last_episode_watched=seasons_eps[-1].episodes,
                                  status=status)
        else:
            user_list = AnimeList(user_id=user_id,
                                  anime_id=element_id,
                                  current_season=1,
                                  last_episode_watched=1,
                                  status=status)

        db.session.add(user_list)
        db.session.commit()
        app.logger.info('[{}] Added an anime with the ID {}'.format(user_id, element_id))
        anime = Anime.query.filter_by(id=element_id).first()
        set_last_update(media_name=anime.name, media_type=list_type, new_status=status)
    elif list_type == ListType.MOVIES:
        # If it contain the "Animation" genre add to "Completed Animation"
        if status == Status.COMPLETED:
            isAnimation = MoviesGenre.query.filter_by(movies_id=element_id, genre="Animation").first()
            if isAnimation:
                status = Status.COMPLETED_ANIMATION
            else:
                status = Status.COMPLETED
        user_list = MoviesList(user_id=user_id,
                               movies_id=element_id,
                               status=status)

        db.session.add(user_list)
        db.session.commit()
        app.logger.info('[{}] Added movie with the ID {}'.format(user_id, element_id))
        movie = Movies.query.filter_by(id=element_id).first()
        set_last_update(media_name=movie.name, media_type=list_type, new_status=status)

    compute_media_time_spent(list_type)


def add_element_in_base(api_id, list_type, element_cat):
    details_data = API_data(API_key=themoviedb_api_key).get_details_data(api_id, list_type)
    actors_data = API_data(API_key=themoviedb_api_key).get_actors_data(api_id, list_type)

    # Check the API response
    if details_data is None or actors_data is None:
        return flash("There was an error fetching the API data, please try again later", "warning")

    # Get the media cover
    media_cover_path = details_data.get("poster_path")

    if media_cover_path:
        media_cover_name = "{}.jpg".format(secrets.token_hex(8))
        isSuccess = API_data().save_api_cover(media_cover_path, media_cover_name, list_type)
        if isSuccess is False:
            media_cover_name = "default.jpg"
    else:
        media_cover_name = "default.jpg"

    if list_type != ListType.MOVIES:
        name = details_data.get("name", "Unknown") or "Unkwown"
        original_name = details_data.get("original_name", "Unknown") or "Unkwown"
        first_air_date = details_data.get("first_air_date", "Unknown") or "Unkwown"
        last_air_date = details_data.get("last_air_date", "Unknown") or "Unkwown"
        homepage = details_data.get("homepage", "Unknown") or "Unkwown"
        in_production = details_data.get("in_production", False) or False
        total_seasons = details_data.get("number_of_seasons", 0) or 0
        total_episodes = details_data.get("number_of_episodes", 0) or 0
        status = details_data.get("status", "Unknown") or "Unknown"
        vote_average = details_data.get("vote_average", 0) or 0
        vote_count = details_data.get("vote_count", 0) or 0
        synopsis = details_data.get("overview", "Unknown") or "Unknown"
        popularity = details_data.get("popularity", 0) or 0
        themoviedb_id = details_data.get("id")

        # Episode duration: list
        episode_duration = details_data.get("episode_run_time") or None
        if episode_duration is None:
            if list_type == ListType.ANIME:
                episode_duration = 24
            elif list_type == ListType.SERIES:
                episode_duration = 45
        else:
            episode_duration = episode_duration[0]

        # Origin country: list
        origin_country = details_data.get("origin_country", "Unknown") or "Unknown"
        if origin_country != "Unknown":
            origin_country = origin_country[0]

        # Created by: list
        created_by = details_data.get("created_by", "Unknown") or "Unknown"
        if created_by != "Unknown":
            creators = []
            for creator in created_by:
                tmp_created = creator.get("name") or None
                if tmp_created is not None:
                    creators.append(tmp_created)
            created_by = ", ".join(x for x in creators)

        # Seasons: list. Check if a special season exist, if so, ignore it
        seasons = details_data.get('seasons') or None
        seasons_data = []
        if seasons:
            if details_data["seasons"][0]["season_number"] == 0:
                for i in range(1, len(details_data["seasons"])):
                    seasons_data.append(details_data["seasons"][i])
            else:
                for i in range(0, len(details_data["seasons"])):
                    seasons_data.append(details_data["seasons"][i])

        # Genres: list
        genres = details_data.get('genres') or None
        genres_data = []
        if genres:
            for i in range(0, len(details_data.get("genres", []))):
                genres_data.append([details_data["genres"][i]["name"], int(details_data["genres"][i]["id"])])

        # Network: list
        networks = details_data.get('networks') or None
        networks_data = []
        if networks:
            for i in range(0, len(details_data.get("networks", []))):
                networks_data.append(details_data["networks"][i]["name"])
                if i == 4:
                    break

        # Actors names: list
        actors = actors_data.get('cast') or None
        actors_names = []
        if actors:
            for i in range(0, len(actors_data.get("cast", []))):
                actors_names.append(actors_data["cast"][i]["name"])
                if i == 4:
                    break

        # Add the element to the database
        if list_type == ListType.SERIES:
            element = Series(name=name,
                             original_name=original_name,
                             image_cover=media_cover_name,
                             first_air_date=first_air_date,
                             last_air_date=last_air_date,
                             homepage=homepage,
                             in_production=in_production,
                             created_by=created_by,
                             total_seasons=total_seasons,
                             total_episodes=total_episodes,
                             episode_duration=episode_duration,
                             origin_country=origin_country,
                             status=status,
                             vote_average=vote_average,
                             vote_count=vote_count,
                             synopsis=synopsis,
                             popularity=popularity,
                             themoviedb_id=themoviedb_id,
                             last_update=datetime.utcnow())
        elif list_type == ListType.ANIME:
            element = Anime(name=name,
                            original_name=original_name,
                            image_cover=media_cover_name,
                            first_air_date=first_air_date,
                            last_air_date=last_air_date,
                            homepage=homepage,
                            in_production=in_production,
                            created_by=created_by,
                            total_seasons=total_seasons,
                            total_episodes=total_episodes,
                            episode_duration=episode_duration,
                            origin_country=origin_country,
                            status=status,
                            vote_average=vote_average,
                            vote_count=vote_count,
                            synopsis=synopsis,
                            popularity=popularity,
                            themoviedb_id=themoviedb_id,
                            last_update=datetime.utcnow())

        db.session.add(element)
        db.session.commit()

        # Add Actors
        if list_type == ListType.SERIES:
            if len(actors_names) == 0:
                actors = SeriesActors(series_id=element.id,
                                      name="Unknown")
                db.session.add(actors)
            else:
                for name in actors_names:
                    actors = SeriesActors(series_id=element.id,
                                          name=name)
                    db.session.add(actors)
        elif list_type == ListType.ANIME:
            if len(actors_names) == 0:
                actors = AnimeActors(anime_id=element.id,
                                     name="Unknown")
                db.session.add(actors)
            else:
                for name in actors_names:
                    actors = AnimeActors(anime_id=element.id,
                                         name=name)
                    db.session.add(actors)

        # Add genres
        if list_type == ListType.SERIES:
            if len(genres_data) == 0:
                genre = SeriesGenre(series_id=element.id,
                                    genre="Unknown",
                                    genre_id=0)
                db.session.add(genre)
            else:
                for i in range(0, len(genres_data)):
                    genre = SeriesGenre(series_id=element.id,
                                        genre=genres_data[i][0],
                                        genre_id=genres_data[i][1])
                    db.session.add(genre)
        elif list_type == ListType.ANIME:
            try:
                response = requests.get("https://api.jikan.moe/v3/search/anime?q={0}".format(element_data["name"]))
                data_mal = json.loads(response.text)
                mal_id = data_mal["results"][0]["mal_id"]

                response = requests.get("https://api.jikan.moe/v3/anime/{}".format(mal_id))
                data_mal = json.loads(response.text)
                genres = data_mal["genres"]

                for genre in genres:
                    add_genre = AnimeGenre(anime_id=element.id,
                                           genre=genre["name"],
                                           genre_id=int(genre["mal_id"]))
                    db.session.add(add_genre)
            except:
                if len(genres_data) == 0:
                    add_genre = AnimeGenre(anime_id=element.id,
                                            genre="Unknown",
                                            genre_id=0)
                    db.session.add(add_genre)
                else:
                    for i in range(0, len(genres_data)):
                        add_genre = AnimeGenre(anime_id=element.id,
                                               genre=genres_data[i][0],
                                               genre_id=genres_data[i][1])
                        db.session.add(add_genre)

        # Add networks
        if list_type == ListType.SERIES:
            if len(networks_data) == 0:
                network = SeriesNetwork(series_id=element.id,
                                        network="Unknown")
                db.session.add(network)
            else:
                for network_data in networks_data:
                    network = SeriesNetwork(series_id=element.id,
                                            network=network_data)
                    db.session.add(network)
        elif list_type == ListType.ANIME:
            if len(networks_data) == 0:
                network = AnimeNetwork(anime_id=element.id,
                                       network="Unknown")
                db.session.add(network)
            else:
                for network_data in networks_data:
                    network = AnimeNetwork(anime_id=element.id,
                                           network=network_data)
                    db.session.add(network)

        # Add number of episodes for each season
        if seasons_data == []:
            if list_type == ListType.SERIES:
                season = SeriesEpisodesPerSeason(series_id=element.id,
                                                 season=1,
                                                 episodes=1)
            elif list_type == ListType.ANIME:
                season = AnimeEpisodesPerSeason(anime_id=element.id,
                                                season=1,
                                                episodes=1)
        else:
            for season_data in seasons_data:
                if list_type == ListType.SERIES:
                    season = SeriesEpisodesPerSeason(series_id=element.id,
                                                     season=season_data["season_number"],
                                                     episodes=season_data["episode_count"])
                elif list_type == ListType.ANIME:
                    season = AnimeEpisodesPerSeason(anime_id=element.id,
                                                    season=season_data["season_number"],
                                                    episodes=season_data["episode_count"])
                db.session.add(season)

        db.session.commit()
    elif list_type == ListType.MOVIES:
        name = details_data.get("title", "Unknown")
        original_name = details_data.get("original_title", "Unknown")
        release_date = details_data.get("release_date", "Unknown")
        homepage = details_data.get("homepage", "Unknown")
        released = details_data.get("status", False)
        vote_average = details_data.get("vote_average", 0)
        vote_count = details_data.get("vote_count", 0)
        synopsis = details_data.get("overview", "Unknown")
        popularity = details_data.get("popularity", 0)
        budget = details_data.get("budget", 0)
        revenue = details_data.get("revenue", 0)
        tagline = details_data.get("tagline", "Unknown")
        themoviedb_id = details_data.get("id")
        runtime = element_data.get("runtime", 0)
        original_language = element_data.get("original_language", "Unknown")
        collection_id = details_data.get("belongs_to_collection") or None

        # Collection data
        if collection_id:
            collection_data = API_data(API_key=themoviedb_api_key).get_collection_data(collection_id)
            collection_parts = len(collection_data.get('parts'))
            collection_name = collection_data.get('name')
            collection_overview = collection_data.get('overview')

            # Get the collection media cover
            collection_cover_path = collection_data.get("poster_path")
            if collection_cover_path:
                collection_cover_name = "{}.jpg".format(secrets.token_hex(8))
                isSuccess = API_data().save_api_cover(collection_cover_path, collection_cover_name, ListType.MOVIES,
                                                      collection=True)
                if isSuccess is False:
                    collection_cover_name = "default.jpg"
            else:
                collection_cover_name = "default.jpg"

            # Add the element to the database
            add_collection = MoviesCollections(collection_id=collection_id,
                                               parts=collection_parts,
                                               name=collection_name,
                                               poster=collection_cover_name,
                                               overview=collection_overview)

            db.session.add(add_collection)
            db.session.commit()

        # Actors names
        actors = actors_data.get('cast') or None
        actors_names = []
        if actors:
            for i in range(0, len(actors_data.get("cast", []))):
                actors_name.append(actors_data["cast"][i]["name"])
                if i == 4:
                    break

        # Genres
        genres = details_data.get('genres') or None
        genres_data = []
        if genres:
            for i in range(0, len(details_data.get("genres", []))):
                genres_data.append([details_data["genres"][i]["name"],int(details_data["genres"][i]["id"])])

        # Production companies
        prod = details_data.get('production_companies') or None
        production_companies = []
        if prod:
            for i in range(0, len(details_data.get("production_companies", []))):
                production_companies.append(details_data["production_companies"][i]["name"])

        # Add the element to the database
        element = Movies(name=name,
                         original_name=original_name,
                         image_cover=media_cover_name,
                         release_date=release_date,
                         homepage=homepage,
                         released=released,
                         runtime=runtime,
                         original_language=original_language,
                         vote_average=vote_average,
                         vote_count=vote_count,
                         synopsis=synopsis,
                         popularity=popularity,
                         budget=budget,
                         revenue=revenue,
                         tagline=tagline,
                         themoviedb_id=themoviedb_id,
                         collection_id=collection_id)

        db.session.add(element)
        db.session.commit()

        # Add Actors
        if len(actors_names) == 0:
            actors = MoviesActors(movies_id=element.id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for name in actors_names:
                actors = MoviesActors(movies_id=element.id,
                                      name=name)
                db.session.add(actors)

        # Add genres
        if len(genres_data) == 0:
            genre = MoviesGenre(movies_id=element.id,
                                genre="Unknown",
                                genre_id=0)
            db.session.add(genre)
        else:
            for i in range(0, len(genres_data)):
                genre = MoviesGenre(movies_id=element.id,
                                    genre=genres_data[i][0],
                                    genre_id=genres_id[i][1])
                db.session.add(genre)

        # Add production companies
        if len(production_companies) == 0:
            company = MoviesProd(movies_id=element.id,
                                 production_company="Unknown")
            db.session.add(company)
        else:
            for prod_company in production_companies:
                company = MoviesProd(movies_id=element.id,
                                     production_company=prod_company)
                db.session.add(company)

        db.session.commit()

    add_element_to_user(element.id, current_user.id, list_type, element_cat)


def save_profile_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.root_path, 'static/profile_pics', picture_fn)
    try:
        i = Image.open(form_picture)
    except:
        return "default.jpg"
    i = i.resize((300, 300), Image.ANTIALIAS)
    i.save(picture_path, quality=90)

    return picture_fn


def add_follow(follow_username):
    follow_to_add = User.query.filter_by(username=follow_username).first()

    if follow_to_add is None or follow_to_add.id == 1:
        app.logger.info('[{}] Attempt to follow user {}'.format(current_user.id, follow_username))
        return flash('This user does not exist', 'warning')

    if follow_to_add.username is current_user.username:
        return flash("You can't follow yourself", 'warning')
    else:
        follow_exists = Follow.query.filter_by(user_id=current_user.id, follow_id=follow_to_add.id).first()

        if follow_exists:
            return flash('User already in your follow list', 'info')

        add_follow = Follow(user_id   = current_user.id,
                            follow_id = follow_to_add.id)

        db.session.add(add_follow)
        db.session.commit()

        app.logger.info('[{}] is following the user with ID {}'.format(current_user.id, follow_to_add.id))
        flash("Follow successfully added.", 'success')


def send_reset_email(user):
    token = user.get_reset_token()
    msg = Message(subject    = 'Password Reset Request',
                  sender     = app.config['MAIL_USERNAME'],
                  recipients = [user.email],
                  bcc        = [app.config['MAIL_USERNAME']],
                  reply_to   = app.config['MAIL_USERNAME'])

    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\emails\\password_reset.html")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/emails/password_reset.html")

    email_template = open(path, 'r').read().replace("{1}", user.username)
    email_template = email_template.replace("{2}", url_for('reset_token', token=token, _external=True))
    msg.html = email_template

    try:
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error('[SYSTEM] Exception raised when sending reset email to user with the ID {} : {}'
                         .format(user.id, e))
        return False


def send_register_email(user):
    token = user.get_register_token()
    msg = Message(subject    = 'MyLists Register Request',
                  sender     = app.config['MAIL_USERNAME'],
                  recipients = [user.email],
                  bcc        = [app.config['MAIL_USERNAME']],
                  reply_to   = app.config['MAIL_USERNAME'])

    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\emails\\register.html")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/emails/register.html")

    email_template = open(path, 'r').read().replace("{1}", user.username)
    email_template = email_template.replace("{2}", url_for('register_account_token', token=token, _external=True))
    msg.html = email_template

    try:
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error('[SYSTEM] Exception raised when sending register email to user with the ID {} : {}'
                         .format(user.id, e))
        return False


def send_email_update_email(user):
    token = user.get_email_update_token()
    msg = Message(subject    = 'MyList Email Update Request',
                  sender     = app.config['MAIL_USERNAME'],
                  recipients = [user.email],
                  bcc        = [app.config['MAIL_USERNAME']],
                  reply_to   = app.config['MAIL_USERNAME'])

    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\emails\\email_update.html")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/emails/email_update.html")

    email_template = open(path, 'r').read().replace("{1}", user.username)
    email_template = email_template.replace("{2}", url_for('email_update_token', token=token, _external=True))
    msg.html = email_template

    try:
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error('[SYSTEM] Exception raised when sending email update email to user with the ID {} : {}'
                         .format(user.id, e))
        return False


def refresh_db_badges():
    list_all_badges = []
    path = os.path.join(app.root_path, 'static/csv_data/badges.csv')
    with open(path, "r") as fp:
        for line in fp:
            list_all_badges.append(line.split(";"))

    badges = Badges.query.order_by(Badges.id).all()
    for i in range(1, len(list_all_badges)):
        try:
            genre_id = str(list_all_badges[i][4])
        except:
            genre_id = None
        badges[i-1].threshold  = int(list_all_badges[i][0])
        badges[i-1].image_id   = list_all_badges[i][1]
        badges[i-1].title      = list_all_badges[i][2]
        badges[i-1].type       = list_all_badges[i][3]
        badges[i-1].genres_id  = genre_id


############################################### Add data Retroactively #################################################


def add_badges_to_db():
    list_all_badges = []
    path = os.path.join(app.root_path, 'static/csv_data/badges.csv')
    with open(path, "r") as fp:
        for line in fp:
            list_all_badges.append(line.split(";"))

    for i in range(1, len(list_all_badges)):
        try:
            genre_id = str(list_all_badges[i][4])
        except:
            genre_id = None
        badge = Badges(threshold=int(list_all_badges[i][0]),
                       image_id=list_all_badges[i][1],
                       title=list_all_badges[i][2],
                       type=list_all_badges[i][3],
                       genres_id=genre_id)
        db.session.add(badge)


def add_actors_movies():
    all_movies = Movies.query.all()
    for i in range(0, len(all_movies)):
        tmdb_movies_id = all_movies[i].themoviedb_id
        movies_id = all_movies[i].id
        response = requests.get("https://api.themoviedb.org/3/movie/{0}/credits?api_key={1}"
                                .format(tmdb_movies_id, themoviedb_api_key))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = MoviesActors(movies_id=movies_id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = MoviesActors(movies_id=movies_id,
                                      name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


def add_collections_movies():
    if platform.system() == "Windows":
        local_covers_path = os.path.join(app.root_path, "static\\covers\\movies_collection_covers\\")
    else: # Linux & macOS
        local_covers_path = os.path.join(app.root_path, "static/covers/movies_collection_covers/")

    all_movies = Movies.query.all()
    for movie in all_movies:
        tmdb_movies_id = movie.themoviedb_id
        try:
            response = requests.get("https://api.themoviedb.org/3/movie/{0}?api_key={1}"
                                    .format(tmdb_movies_id, themoviedb_api_key))

            data = json.loads(response.text)

            collection_id = data["belongs_to_collection"]["id"]
            collection_poster = data["belongs_to_collection"]["poster_path"]

            response_collection = requests.get("https://api.themoviedb.org/3/collection/{0}?api_key={1}"
                                               .format(collection_id, themoviedb_api_key))

            data_collection = json.loads(response_collection.text)

            collection_name = data_collection["name"]
            collection_overview = data_collection["overview"]
            collection_parts = len(data_collection["parts"])

            collection_poster_id = "{}.jpg".format(secrets.token_hex(8))

            urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{}".format(collection_poster),
                                       "{}{}".format(local_covers_path, collection_poster_id))

            img = Image.open("{}{}".format(local_covers_path, collection_poster_id))
            img = img.resize((300, 450), Image.ANTIALIAS)
            img.save("{0}{1}".format(local_covers_path, collection_poster_id), quality=90)
        except:
            continue

        movie.collection_id = collection_id

        # Test if collection already in MoviesCollection
        if MoviesCollections.query.filter_by(collection_id=collection_id).first() is not None:
            db.session.commit()
            continue

        add_collection = MoviesCollections(collection_id=collection_id,
                                           parts=collection_parts,
                                           name=collection_name,
                                           poster=collection_poster_id,
                                           overview=collection_overview)

        db.session.add(add_collection)
        db.session.commit()


def add_actors_series():
    all_series = Series.query.all()
    for i in range(0, len(all_series)):
        tmdb_series_id = all_series[i].themoviedb_id
        series_id = all_series[i].id
        response = requests.get("https://api.themoviedb.org/3/tv/{0}/credits?api_key={1}"
                                .format(tmdb_series_id, themoviedb_api_key))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = SeriesActors(series_id=series_id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = SeriesActors(series_id=series_id,
                                      name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


def add_actors_anime():
    all_anime = Anime.query.all()
    for i in range(0, len(all_anime)):
        tmdb_anime_id = all_anime[i].themoviedb_id
        anime_id = all_anime[i].id
        response = requests.get("https://api.themoviedb.org/3/tv/{0}/credits?api_key={1}"
                                .format(tmdb_anime_id, themoviedb_api_key))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = AnimeActors(anime_id=anime_id,
                                 name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = AnimeActors(anime_id=anime_id,
                                     name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


############################################# TMDb API Update Scheduler ################################################


def refresh_element_data(api_id, list_type):
    details_data = API_data(API_key=themoviedb_api_key).get_details_data(api_id, list_type)

    if list_type == ListType.SERIES:
        element = Series.query.filter_by(themoviedb_id=api_id).first()
    elif list_type == ListType.ANIME:
        element = Anime.query.filter_by(themoviedb_id=api_id).first()
    elif list_type == ListType.MOVIES:
        element = Movies.query.filter_by(themoviedb_id=api_id).first()

    if details_data is None or element is None:
        app.logger.info('[SYSTEM] Could not refresh the element with the TMDb ID {}'.format(api_id))
    else:
        if list_type != ListType.MOVIES:
            name = details_data.get("name", "Unknown") or "Unkwown"
            original_name = details_data.get("original_name", "Unknown") or "Unkwown"
            first_air_date = details_data.get("first_air_date", "Unknown") or "Unkwown"
            last_air_date = details_data.get("last_air_date", "Unknown") or "Unkwown"
            homepage = details_data.get("homepage", "Unknown") or "Unkwown"
            in_production = details_data.get("in_production", False) or False
            total_seasons = details_data.get("number_of_seasons", 0) or 0
            total_episodes = details_data.get("number_of_episodes", 0) or 0
            status = details_data.get("status", "Unknown") or "Unknown"
            vote_average = details_data.get("vote_average", 0) or 0
            vote_count = details_data.get("vote_count", 0) or 0
            synopsis = details_data.get("overview", "Unknown") or "Unknown"
            popularity = details_data.get("popularity", 0) or 0

            try:
                poster_path = details_data["poster_path"]
            except:
                poster_path = ""

            # Refresh Created by
            try:
                created_by = ', '.join(x['name'] for x in details_data['created_by'])
                if created_by == "":
                    created_by = "Unknown"
            except:
                created_by = "Unknown"

            # Refresh Episode duration
            try:
                episode_duration = details_data["episode_run_time"][0]
                if episode_duration == "":
                    if list_type == ListType.ANIME:
                        episode_duration = 24
                    else:
                        episode_duration = 45
            except:
                if list_type == ListType.ANIME:
                    episode_duration = 24
                else:
                    episode_duration = 45

            # Refresh Origin country
            try:
                origin_country = ", ".join(details_data["origin_country"])
                if origin_country == "":
                    origin_country = "Unknown"
            except:
                origin_country = "Unknown"

            # Refresh if a special season exist, we do not want to take it into account
            seasons_data = []
            if len(details_data["seasons"]) == 0:
                return None

            if details_data["seasons"][0]["season_number"] == 0:
                for i in range(len(details_data["seasons"])):
                    try:
                        seasons_data.append(details_data["seasons"][i + 1])
                    except:
                        pass
            else:
                for i in range(len(details_data["seasons"])):
                    try:
                        seasons_data.append(details_data["seasons"][i])
                    except:
                        pass

            # Refresh the cover
            if list_type == ListType.SERIES:
                if platform.system() == "Windows":
                    local_covers_path = os.path.join(app.root_path, "static\\covers\\series_covers\\")
                else:  # Linux & macOS
                    local_covers_path = os.path.join(app.root_path, "static/covers/series_covers/")
            elif list_type == ListType.ANIME:
                if platform.system() == "Windows":
                    local_covers_path = os.path.join(app.root_path, "static\\covers\\anime_covers\\")
                else:  # Linux & macOS
                    local_covers_path = os.path.join(app.root_path, "static/covers/anime_covers/")

            try:
                if poster_path != "":
                    urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{0}".format(poster_path),
                                               "{}{}".format(local_covers_path, element.image_cover))

                    img = Image.open(local_covers_path + element.image_cover)
                    img = img.resize((300, 450), Image.ANTIALIAS)
                    img.save(local_covers_path + element.image_cover, quality=90)
            except:
                app.logger.info("Error while refreshing the cover of ID {}".format(element.id))
                pass

            # Refresh the data for Anime/Series
            element.name = name
            element.original_name = original_name
            element.first_air_date = first_air_date
            element.last_air_date = last_air_date
            element.homepage = homepage
            element.in_production = in_production
            element.created_by = created_by
            element.episode_duration = episode_duration
            element.total_seasons = total_seasons
            element.total_episodes = total_episodes
            element.origin_country = origin_country
            element.status = status
            element.vote_average = vote_average
            element.vote_count = vote_count
            element.synopsis = synopsis
            element.popularity = popularity

            # Update the number of seasons and episodes
            for season_data in seasons_data:
                if list_type == ListType.SERIES:
                    season = SeriesEpisodesPerSeason.query.filter_by(series_id=element.id,
                                                                     season=season_data["season_number"]).first()
                    if season is None:
                        season = SeriesEpisodesPerSeason(series_id=element.id,
                                                         season=season_data["season_number"],
                                                         episodes=season_data["episode_count"])
                        db.session.add(season)
                    else:
                        season.episodes = season_data["episode_count"]
                elif list_type == ListType.ANIME:
                    season = AnimeEpisodesPerSeason.query.filter_by(anime_id=element.id,
                                                                    season=season_data["season_number"]).first()
                    if season is None:
                        season = AnimeEpisodesPerSeason(anime_id=element.id,
                                                        season=season_data["season_number"],
                                                        episodes=season_data["episode_count"])
                        db.session.add(season)
                    else:
                        season.episodes = season_data["episode_count"]

            # TODO: Refresh networks, genres and actors
            element.last_update = datetime.utcnow()
            db.session.commit()
            app.logger.info("[SYSTEM] Refreshed the series/anime with the ID {}".format(element.id))
        elif list_type == ListType.MOVIES:
            release_date = details_data.get("release_date", "Unknown")
            homepage = details_data.get("homepage", "Unknown")
            released = details_data.get("status", False)
            vote_average = details_data.get("vote_average", 0)
            vote_count = details_data.get("vote_count", 0)
            synopsis = details_data.get("overview", "Unknown")
            popularity = details_data.get("popularity", 0)
            budget = details_data.get("budget", 0)
            revenue = details_data.get("revenue", 0)
            tagline = details_data.get("tagline", "Unknown")
            runtime = element_data.get("runtime", 0)
            original_language = element_data.get("original_language", "Unknown")
            collection_id = details_data.get("belongs_to_collection") or None

            try:
                poster_path = details_data["poster_path"]
            except:
                poster_path = ""

            # Refresh runtime
            try:
                runtime = details_data["runtime"]
                if runtime == None or runtime == "":
                    runtime = 90
            except:
                runtime = 90

            # Refresh original language
            try:
                original_language = details_data["original_language"]
                if original_language == "":
                    original_language = "Unknown"
            except:
                original_language = "Unknown"

            # Refresh the cover
            if platform.system() == "Windows":
                local_covers_path = os.path.join(app.root_path, "static\\covers\\movies_covers\\")
            else:  # Linux & macOS
                local_covers_path = os.path.join(app.root_path, "static/covers/movies_covers/")

            try:
                if poster_path != "":
                    urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{0}".format(poster_path),
                                               "{}{}".format(local_covers_path, element.image_cover))

                    img = Image.open(local_covers_path + element.image_cover)
                    img = img.resize((300, 450), Image.ANTIALIAS)
                    img.save(local_covers_path + element.image_cover, quality=90)
            except:
                app.logger.info("Error while refreshing the movie cover of ID {}".format(element.id))
                pass

            # Refresh the movies data
            element.release_date = release_date
            element.released = released
            element.homepage = homepage
            element.runtime = runtime
            element.original_language = original_language
            element.vote_average = vote_average
            element.vote_count = vote_count
            element.synopsis = synopsis
            element.popularity = popularity
            element.budget = budget
            element.revenue = revenue
            element.tagline = tagline
            element.collection_id = collection_id

            # TODO: Refresh production companies, genres and actors
            db.session.commit()
            app.logger.info("[SYSTEM] Refreshed the movie with the ID {}".format(element.id))


def automatic_media_refresh():
    app.logger.info('[SYSTEM] Starting automatic refresh')

    # Recover all the data
    all_movies = Movies.query.all()
    all_series = Series.query.all()
    all_anime  = Anime.query.all()

    # Create a list containing all the Movies TMDb ID
    all_movies_tmdb_id_list = []
    for movie in all_movies:
        all_movies_tmdb_id_list.append(movie.themoviedb_id)

    # Create a list containing all the Series TMDb ID
    all_series_tmdb_id_list = []
    for series in all_series:
        all_series_tmdb_id_list.append(series.themoviedb_id)

    # Create a list containing all the Anime TMDb ID
    all_anime_tmdb_id_list = []
    for anime in all_anime:
        all_anime_tmdb_id_list.append(anime.themoviedb_id)

    # Recover from API all the changed Movies ID
    try:
        response = requests.get("https://api.themoviedb.org/3/movie/changes?api_key={0}"
                                .format(themoviedb_api_key))
    except Exception as e:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : {}'.format(e))
        return
    if response.status_code == 401:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
        return

    try:
        all_id_movies_changes = json.loads(response.text)
    except:
        return

    # Recover from API all the changed series/anime ID
    try:
        response = requests.get("https://api.themoviedb.org/3/tv/changes?api_key={0}"
                                .format(themoviedb_api_key))
    except Exception as e:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : {}'.format(e))
        return
    if response.status_code == 401:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
        return

    try:
        all_id_TV_changes = json.loads(response.text)
    except:
        return

    # Funtion to refresh movies
    for element in all_id_movies_changes["results"]:
        if element["id"] in all_movies_tmdb_id_list:
            refresh_element_data(element["id"], ListType.MOVIES)

    # Funtion to refresh series
    for element in all_id_TV_changes["results"]:
        if element["id"] in all_series_tmdb_id_list:
            refresh_element_data(element["id"], ListType.SERIES)

    # Funtion to refresh anime
    for element in all_id_TV_changes["results"]:
        if element["id"] in all_anime_tmdb_id_list:
            refresh_element_data(element["id"], ListType.ANIME)

    app.logger.info('[SYSTEM] Automatic refresh completed')


app.apscheduler.add_job(func=automatic_media_refresh, trigger='cron', hour=3, id="{}".format(secrets.token_hex(8)))
