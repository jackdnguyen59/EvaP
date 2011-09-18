from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.datastructures import SortedDict
from django.utils.translation import ugettext as _

from evaluation.models import Course, Semester

import xlrd


class UserData(object):
    """Holds information about a user, retrieved from the Excel file."""
    
    def __init__(self, username=None, first_name=None, last_name=None, title=None):
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.title = title
    
    def store_in_database(self):
        user = User(username=self.username,
                    first_name=self.first_name,
                    last_name=self.last_name)
        user.save()
        profile = user.get_profile()
        profile.title = self.title
        profile.save()
        return user


class CourseData(object):
    """Holds information about a course, retrieved from the Excel file."""
    
    def __init__(self, name_de=None, name_en=None, kind=None):
        self.name_de = name_de
        self.name_en = name_en
        self.kind = kind
    
    def store_in_database(self, vote_start_date, vote_end_date, semester):
        course = Course(name_de=self.name_de,
                        name_en=self.name_en,
                        kind=self.kind,
                        vote_start_date=vote_start_date,
                        vote_end_date=vote_end_date,
                        semester=semester)
        course.save()
        return course


class ExcelImporter(object):
    def __init__(self, request):
        self.associations = SortedDict()
        self.request = request
    
    def read_file(self, excel_file):
        """Reads an excel file and stores all the student-lecturer-course
        associations in the `associations` member."""
        
        book = xlrd.open_workbook(file_contents=excel_file.read())
        
        # read the file row by row, sheet by sheet
        for sheet in book.sheets():
            try:
                for row in range(1, sheet.nrows):
                    data = sheet.row_values(row)
                    # assign data to data objects
                    student_data = UserData(username=data[3], first_name=data[2], last_name=data[1])
                    lecturer_data = UserData(username=data[9], first_name="", last_name=data[8], title=data[7])
                    course_data = CourseData(name_de=data[5], name_en=data[6], kind=data[4])
                    
                    # store data objects together with the data source location for problem tracking
                    self.associations[(sheet.name, row)] = (student_data, lecturer_data, course_data)
                messages.info(self.request, _(u"Successfully read sheet '%s'.") % sheet.name)
            except:
                messages.warning(self.request, _(u"A problem occured while reading sheet '%s'.") % sheet.name)
                raise
        messages.info(self.request, _(u"Successfully read excel file."))
    
    def validate_and_fix(self):
        """Validates the internal integrity of the data read by read_file and
        fixes and inferres data if possible. Should not validate against data
        already in the database."""
        
        for (sheet, row), (student_data, lecturer_data, course_data) in self.associations.items():
            # try to infer first names from usernames
            if not lecturer_data.first_name:
                first, sep, last = lecturer_data.username.partition(".")
                if sep == ".":
                    lecturer_data.first_name = first
    
    def save_to_db(self, semester, vote_start_date, vote_end_date):
        """Stores the read and validated data in the database. Errors might still
        occur because the previous validation does check not for consistency with
        the data already in the database."""
        
        with transaction.commit_on_success():
            course_count = 0
            student_count = 0
            lecturer_count = 0
            for (sheet, row), (student_data, lecturer_data, course_data) in self.associations.items():
                try:
                    # create or retrieve database objects
                    try:
                        student = User.objects.get(username=student_data.username)
                    except User.DoesNotExist:
                        student = student_data.store_in_database()
                        student_count += 1
                    
                    try:
                        lecturer = User.objects.get(username=lecturer_data.username)
                    except User.DoesNotExist:
                        lecturer = lecturer_data.store_in_database()
                        lecturer_count += 1
                    
                    try:
                        course = Course.objects.get(semester=semester, name_de=course_data.name_de)
                    except Course.DoesNotExist:
                        course = course_data.store_in_database(vote_start_date, vote_end_date, semester)
                        course_count += 1
                    
                    # connect database objects
                    course.participants.add(student)
                    course.primary_lecturers.add(lecturer)
                    
                except Exception, e:
                    messages.warning(self.request, _("A problem occured while writing the entries to the database. " \
                                                     "The original data location was row %(row)d of sheet '%(sheet)s'. " \
                                                     "The error message has been: '%(error)s'") % dict(row=row, sheet=sheet, error=e))
                    raise
            messages.info(self.request, _("Successfully created %(courses)d course(s), %(students)d student(s) and %(lecturers)d lecturer(s).") %
                                            dict(courses=course_count, students=student_count, lecturers=lecturer_count))
    
    @classmethod
    def process(cls, request, excel_file, semester, vote_start_date, vote_end_date):
        """Entry point for the view."""
        try:
            importer = cls(request)
            importer.read_file(excel_file)
            importer.validate_and_fix()
            importer.save_to_db(semester, vote_start_date, vote_end_date)
        except Exception, e:
            messages.error(request, _(u"Import finally aborted after exception: '%s'" % e))
