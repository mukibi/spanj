#!/usr/bin/perl

use strict;
use warnings;
use feature "switch";

use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

my $con;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		my $id = $session{"id"};
		if ($id eq "1") {
			$authd++;
		}
	}
}

my $content = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/yans/">Yans Timetable Builder</a> --&gt; <a href="/cgi-bin/edittimetableprofiles.cgi">Edit Timetable Profiles</a>
	<hr> 
};


unless ($authd) {
	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Timetable Profile</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to edit timetable profiles.</span> Only the administrator is authorized to take this action.
</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/edittimetableprofiles.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Yans: Timetable Builder - Timetable Profile</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/edittimetableprofiles.cgi">/login.html?cont=/cgi-bin/edittimetableprofiles.cgi</a>. If you were not, <a href="/cgi-bin/edittimetableprofiles.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

#mode 0 is
#'list all existing profiles + opt to create a new one'
my $mode = 0;
my $profile;

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?profile=([0-9A-Z]+)\&?/i ) {
		$profile = $1;
		#mode 1 is
		#'display selected profile for editing'
		#or validate & save posted data
		$mode = 1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=new\&?/i ) {
		#mode 2 is
		#'display options for creating a new profile'
		$mode = 2;
	}
}

my $post_mode = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	
	my $str = "";

	while (<STDIN>) {
               	$str .= $_;
       	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
	my @auth_req = split/&/,$str;

	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");	
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
	}
	}
	#processing data sent 
	$post_mode++;
}

my @today = localtime;
my $current_yr = $today[5] + 1900;

#read vars for 'classes' and 'subjects'
#variables

my $yrs_study = 4;
my @classes = ("1", "2", "3", "4");
my @subjects = ("Mathematics", "English", "Kiswahili", "History", "CRE", "Geography", "Physics", "Chemistry", "Biology", "Computers", "Business Studies", "Home Science");
my %existing_profiles = ();

$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		

if ($con) {
	my $prep_stmt0 = $con->prepare("SELECT id,value FROM vars WHERE id='1-classes' OR id='1-subjects' LIMIT 2");
	if ($prep_stmt0) {
		my $rc = $prep_stmt0->execute();	
		if ($rc) {
			while ( my @valid = $prep_stmt0->fetchrow_array() ) {
				#classes 
				if ($valid[0] eq "1-classes") {
					my ($min_class, $max_class) = (undef,undef);
					@classes  =  split/,\s*/, $valid[1];
					foreach (@classes) {
						if ($_ =~ /(\d+)/) {
							my $tst_yr = $1;
							if (not defined $min_class) {
								$min_class = $tst_yr;
								$max_class = $tst_yr;
							}
							else {
								$min_class = $tst_yr if ($tst_yr < $min_class);
								$max_class = $tst_yr if ($tst_yr > $max_class);
							}
						}
						$yrs_study = ($max_class - $min_class) + 1;
					}	
				}
				#subjects
				else {
					@subjects = split/,\s*/, $valid[1];
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt0->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt0->errstr, $/;  
	}

	#read profiles	
	my $prep_stmt1 = $con->prepare("SELECT table_name, profile_name, creation_time FROM profiles");
	if ($prep_stmt1) {
		my $rc = $prep_stmt1->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt1->fetchrow_array() ) {
				$existing_profiles{$rslts[0]} = {"name" => $rslts[1], "time" => $rslts[2]};
			}
		}
	}
	else {
		print STDERR "Could not create SELECT FROM profiles statement: ", $con->errstr, $/;
	}
}

my $feedback = ""; 
#process posted data

if ($post_mode) {

	EDIT_EXISTING: {	
	if ($mode == 1) {
		unless (defined $profile) {
			$feedback = qq%<P><SPAN style="color: red">No profile selected.</SPAN>%;
			$mode = 0;
			last EDIT_EXISTING;
		}
		if (not exists $existing_profiles{$profile}) {
			$feedback = qq%<P><SPAN style="color: red">The profile selected does not exist.</SPAN>%;
			$mode = 0;
			last EDIT_EXISTING;
		}

		my @valid_lessons = ();
		my @valid_subjects = ();

		for my $subject (@subjects) {
			push @valid_subjects, "(?:$subject)";
			for my $class (@classes) {
				push @valid_lessons, "(?:$subject\\($class\\))";
			}
		}	
		my $valid_lessons_str = join("|", @valid_lessons);
		my $valid_subjects_str = join("|", @valid_subjects);

		my @valid_classes = ();

		for my $class (@classes) {
			push @valid_classes, "(?:$class)";
		}
		my $valid_classes_str = join("|", @valid_classes);	

		my $valid_days_str = "(?:Monday)|(?:Tuesday)|(?:Wednesday)|(?:Thursday)|(?:Friday)|(?:Saturday)|(?:Sunday)";

		my %validation_checks = 
(
"days_week" => "^(?:$valid_days_str)(?:,(?:$valid_days_str))*\$",
"add_fixed_scheduling_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"subjects" => "(?:$valid_subjects_str)(?:,(?:$valid_subjects_str))*\$",
"teachers_number_free_mornings" => "^[0-9]+\$",
"lesson_structure_classes_[0-9]+" => "^(?:$valid_classes_str)(?:,(?:$valid_classes_str))*\$",
"exception_days_[0-9]+" => "^(?:$valid_days_str)(?:,(?:$valid_days_str))*\$",
"teachers_number_free_afternoons" => "^[0-9]+\$",
"add_lesson_associations_occasional_joint_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"lesson_structure_struct_[0-9]+" => "^(?:[0-9]+x[0-9]+)(?:,(?:[0-9]+x[0-9]))*\$",
"classes" => "^(?:$valid_classes_str)(?:,(?:$valid_classes_str))*\$",
"lesson_structure_subject_[0-9]+" => "(?:$valid_subjects_str)(?:,(?:$valid_subjects_str))*\$",
"day_organization_[0-9]+" => "^(?:(?:{LESSON})|(?:[^\\[]+\\[[0-9]+\\]))+\$",
"lesson_associations_simultaneous_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"fixed_scheduling_periods_[0-9]+" => "^(?:(?:$valid_days_str)\\([0-9]+(?:,(?:[0-9]+))*\\))(?:;(?:(?:$valid_days_str)\\([0-9]+(?:,(?:[0-9]+))*\\)))*\$",
"lesson_duration" => "^[0-9]+\$",
"lesson_associations_occasional_joint_format_[0-9]+" => "^(?:[0-9]+x[0-9]+)(?:,(?:[0-9]+x[0-9]))*\$",
"fixed_scheduling_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
#note how i allow a minute of 60? Yes, that wasn't accidental--
#here there be leap seconds
"start_lessons_[0-9]+" => "^[012]?[0-9]:?[0-6][0-9]\$",
"add_lesson_associations_mut_ex_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"lesson_associations_mut_ex_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"teachers_maximum_consecutive_lessons" => "^[0-9]+\$",
"maximum_number_doubles" => "^[0-9]+\$",
"add_lesson_associations_consecutive_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"teachers" => "^(?:[0-9]+)(?:,(?:[0-9]+))*\$",
"lesson_associations_occasional_joint_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"lesson_associations_consecutive_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"add_lesson_associations_simultaneous_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$"
);
		
		my @invalid_formats = ();
		my @valid_formats = ();
		my %to_del;

		for my $posted_val (keys %auth_params) {	
			CHECKS: for my $validation_check (keys %validation_checks) {
				if ($posted_val =~ /$validation_check/) {
					if ($auth_params{$posted_val} =~ /^$/) {
						push @valid_formats, $posted_val;
						$to_del{$posted_val}++;
					
						#now find related values
						#lesson_structure_?
						if ($posted_val =~ /^lesson_structure_(?:(?:classes)|(?:struct)|(?:subject))_([0-9]+)$/) {
							my $id = $1;
							$to_del{"lesson_structure_classes_$id"}++;
							$to_del{"lesson_structure_struct_$id"}++;
							$to_del{"lesson_structure_subject_$id"}++;
						}
						#fixed_scheduling_?
						elsif ($posted_val =~ /^fixed_scheduling_(?:(?:periods)|(?:lessons))_([0-9]+)$/) {
							my $id = $1;
							$to_del{"fixed_scheduling_periods_$id"}++;
							$to_del{"fixed_scheduling_lessons_$id"}++;
						}
					#lesson_associations_occasional_joint_?
						elsif ($posted_val =~ /^lesson_associations_occasional_joint_(?:(?:lessons)|(?:format))_([0-9]+)$/) {
							my $id = $1;
							$to_del{"lesson_associations_occasional_joint_lessons_$id"}++;
							$to_del{"lesson_associations_occasional_joint_format_$id"}++;
						}
					}

					elsif ($auth_params{$posted_val} =~ /$validation_checks{$validation_check}/i) {
						push @valid_formats, $posted_val;
					}
					#blanks should be deleted
					else {
						push @invalid_formats, $posted_val;
					}
					last CHECKS;
				}
			}	
		}

		#add_s are handled differently-they require
		#concatenation of the new value & the existing
		#one (if any). That 'if any' is important.
		my @regular_update_placeholders = ();
		my @regular_update_args = ();
			
		my @add_update_args = ();

		my @delete_placeholders = ();
		my @delete_args;

		for my $key (@valid_formats) {
			#ignore del values
			next if (exists $to_del{$key});
	
			if ($key =~ /^add_(.+)$/i) {
				push @add_update_args, $1;
			}
			else {
				push @regular_update_placeholders, "(?,?)";
				push @regular_update_args,$key,$auth_params{$key}; 
			}
		}

		for my $del_key (keys %to_del) {	
			push @delete_placeholders, "name=?";
			push @delete_args, $del_key;
		}

		if ( scalar(@add_update_args) > 0 ) {
			if ($con) {
				my $add_update_stmt = $con->prepare("INSERT INTO `$profile` VALUES (?,?) ON DUPLICATE KEY UPDATE value=CONCAT_WS(',',value,?)");
				if ($add_update_stmt) {	
					for my $add_update_arg (@add_update_args) {
						$add_update_stmt->execute($add_update_arg, $auth_params{"add_$add_update_arg"}, $auth_params{"add_$add_update_arg"});
					}
				}
			}
		}

		if ( scalar(@regular_update_placeholders) > 0 ) {
			my $regular_update_placeholders_str = join(",", @regular_update_placeholders);
			if ($con) {
				my $regular_update_stmt = $con->prepare("REPLACE INTO `$profile` VALUES $regular_update_placeholders_str");
				if ($regular_update_stmt) {	
					$regular_update_stmt->execute(@regular_update_args);
				}
			}
		}
	
		if (scalar(@delete_args) > 0) {

			my $delete_placeholders_str = join(" OR ", @delete_placeholders);
			if ($con) {
				my $delete_stmt = $con->prepare("DELETE FROM `$profile` WHERE $delete_placeholders_str");
				if ($delete_stmt) {
					$delete_stmt->execute(@delete_args);
				}
			}
		}
 
		if ( scalar(@valid_formats) > 0 ) {
			my $edited_fields = join(", ", @valid_formats);
			#log action
			my @today = localtime;
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

        		if ($log_f) {
                		@today = localtime;
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock($log_f, LOCK_EX) or print STDERR "Could not log edit profile due to flock issue: $!$/";

				seek($log_f, 0, SEEK_END);

				my $template_name = "";
				if (defined $profile) {	
					$template_name .= qq%(${$existing_profiles{$profile}}{"name"})%;
				}
        			print $log_f $session{"id"}, " EDIT PROFILE $profile$template_name ($edited_fields) $time\n";

				flock ($log_f, LOCK_UN);
                		close $log_f;
        		}

			else {
				print STDERR "Could not log EDIT PROFILE $session{'id'}: $!\n";
			}

			$con->commit();	
		}

		if (scalar(@invalid_formats) > 0) {
			$feedback .= qq!<p>The following fields were sent with <span style="color: red">invalid values</span>: ! . join(", ", @invalid_formats);
		}
		if (scalar(@valid_formats) > 0) {
			$feedback .= qq!<p>The following fields were <span style="color: green">updated</span>: ! . join(", ", @valid_formats);
		}
		
	}
	}

	#user wants to create a new profile
	if ($mode == 2) {
	CREATE_NEW : {
		unless (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"}) {
			$feedback .= qq%<P><SPAN style="color: red">No authorization token received for this request.</SPAN>%;
			last CREATE_NEW;
		}
		unless ($session{"confirm_code"} eq $auth_params{"confirm_code"}) {
			$feedback .= qq%<P><SPAN style="color: red">Invalid authorization token received.</SPAN>%;
		}
	
		my $table_name = "";
		my $profile_name = "";
		my $template = undef;

		if (exists $auth_params{"profile_name"} and length($auth_params{"profile_name"}) > 0) {
			$profile_name = $auth_params{"profile_name"};
			if (length($profile_name) > 32) {
				$feedback .= qq%<P><SPAN style="color: red">The profile name provided is too long. A valid profile name is 1-32 characters.</SPAN>%;
				last CREATE_NEW;
			}
			#strip html special chars
			if ($profile_name =~ /['"<>]/) {
				$profile_name =~ s/'//g;
				$profile_name =~ s/"//g;
				$profile_name =~ s/<//g;
				$profile_name =~ s/>//g;
				$feedback .= qq%<P><SPAN style="color: red">The profile name contains one or more of the following illegal characters: &#34;, &#39;, &#60;, &#62;</SPAN>%;
			}
		}

		else {
			$feedback .= qq%<P><SPAN style="color: red">No profile name was provided.</SPAN>%;
			last CREATE_NEW;
		}

		if (exists $auth_params{"template"} and length($auth_params{"template"}) > 0) {
			$template = $auth_params{"template"};

			unless ( exists $existing_profiles{$template} ) {	
				$template = undef;
				$feedback .= qq%<P><SPAN style="color: red">Unknown template selected</SPAN>%;
			}
		}

		my $success = 0;

		#create table
		if ($con) {
			$table_name = "";
			J: while (1) {
				$table_name = gen_token(1);
				unless (exists $existing_profiles{$table_name}) {
					last J;
				}
			}
			#create table
			my $prep_stmt2 = $con->prepare("CREATE TABLE `$table_name`(name varchar(64) unique, value varchar(2048))");
			if ($prep_stmt2) {
				my $rc = $prep_stmt2->execute();
				if ($rc) {
					$success++;
					#update profiles table
					my $prep_stmt3 = $con->prepare("REPLACE INTO profiles VALUES(?,?,?)");
					if ($prep_stmt3) {	
						my $time = time;
						my $rc = $prep_stmt3->execute($table_name, $profile_name, $time);
						unless ($rc) {
							print STDERR "Could not execute REPLACE INTO profiles statement: ", $prep_stmt3->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare REPLACE INTO profiles statement: ", $prep_stmt3->errstr, $/;
					}

					if (defined $template) {
					#load data in the template
						my $prep_stmt4 = $con->prepare("REPLACE INTO `$table_name` SELECT name,value FROM $template");
						if ($prep_stmt4) {
							my $rc = $prep_stmt4->execute();
							unless ($rc) {
								print STDERR "No data loaded into profile from template: ", $prep_stmt4->errstr, $/;
							}
						}
					}

					#log action
					my @today = localtime;
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

        				if ($log_f) {
                				@today = localtime;
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock($log_f, LOCK_EX) or print STDERR "Could not log add profile due to flock issue: $!$/";

						seek($log_f, 0, SEEK_END);

						my $template_name = "";
						if (defined $template) {	
							$template_name .= qq%(${$existing_profiles{$template}}{"name"})%;
						}
                				print $log_f $session{"id"}, " ADD PROFILE $profile_name$template_name $time\n";	

						flock ($log_f, LOCK_UN);
                				close $log_f;
        				}

					else {
						print STDERR "Could not log ADD PROFILE $session{'id'}: $!\n";
					}
					$con->commit();
				}
			}
			else {
				print STDERR "Could not prepare CREATE profile TABLE: ", $prep_stmt2->errstr, $/;
			}
		}
		$content .= 
qq%
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable Profile</title>
</head>
<body>
$header
$feedback
%;
		
		if ($success) {
			$content .= qq%<p><em>Your new timetable profile has been created!</em> Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$table_name">edit it now</a>%;
		}
		else {
			$content .= qq%<p><em>Your new timetable profile was NOT created.</em> Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi?act=new">retry this action</a>?%;
		}
		$content .= "</body></html>";
		#to avoid re-checking
		$mode = 4;
	}
	}
}

#display for editing
DISPLAY_FOR_EDITING: {
if ($mode == 1) {
	my $js = '';
	my $body = $feedback;

	#auth tokens
	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	#there's such a profile
	if (exists $existing_profiles{$profile}) {
		
		my @expand_js_bts;
	
		my %profile_vals;

		my $prep_stmt5 = $con->prepare("SELECT name,value FROM `$profile`");
		if ($prep_stmt5) {
			my $rc = $prep_stmt5->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt5->fetchrow_array()) {
					$profile_vals{$rslts[0]} = $rslts[1];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM profile: ", $prep_stmt5->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM profile: ", $prep_stmt5->errstr, $/;
		}

		$content .=
qq%
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Editing Timetable Profile</title>
%;

		#teachers
		my @tas_ids = ();
		my $current_tas = "";
		my $cntr = 0;
		my %selected_tas = ();

		if ( exists $profile_vals{"teachers"} ) {
			my @teachers = split/,/, $profile_vals{"teachers"};
			for my $teacher (@teachers) {
				if ($teacher =~ /^\d+$/) {
					$selected_tas{$teacher}++
				}
			}
		}

		if ($con) {
			my $prep_stmt6 = $con->prepare("SELECT id,name,subjects FROM teachers");
					
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute();
	
				if ($rc) {
					while (my @valid = $prep_stmt6->fetchrow_array()) {
				
						#say English[1A(2016),2A(2015)];Kiswahili[3A(2014)]
						my $machine_class_subjs = $valid[2];
			
						#now i have 
						#[0]: English[1A(2016),2A(2015)]
						#[1]: Kiswahili[3A(2014)]
						my @subj_groups = split/;/, $machine_class_subjs;
						my @reformd_subj_group = ();

						#take English[1A(2016),2A(2015)]
						for my $subj_group (@subj_groups) {
							my ($subj,$classes_str);
					
							if ($subj_group =~ /^([^\[]+)\[([^\]]+)\]$/) {
								#English
								my $subj = $1;
								#1A(2016),2A(2015)
								my $classes_str = $2;	
								#[0]: 1A(2016)
								#[1]: 2A(2015)
								my @classes_list = split/,/, $classes_str;
								my @reformd_classes_list = ();

								#take 1A(2016) 	
								for my $class (@classes_list) {	
									if ($class =~ /\((\d+)\)$/) {	
										my $grad_yr = $1;	

										my $class_dup = $class;
										$class_dup =~ s/\($grad_yr\)//;

										#not graduated yet
										if ($grad_yr >= $current_yr) {
											my $class_yr = $yrs_study - ($grad_yr - $current_yr);
											$class_dup =~ s/\d+/$class_yr/;
										}
										#already graduated
										else {
											$class_dup =~ s/\d+/$yrs_study/;
											$class_dup .= "[Grad class of $grad_yr]";	
										}
										push @reformd_classes_list, $class_dup;
									}
								}
								my $reformd_classes_str = join(", ", @reformd_classes_list);
								push @reformd_subj_group, "$subj($reformd_classes_str)";
							}
						}
	
						my $human_class_subjs = join("<br>", @reformd_subj_group);
	
						$cntr++;
						push @tas_ids, $valid[0];

						my $checked = '';
						if (exists $selected_tas{$valid[0]}) {
							$checked = ' checked';
						}

						$current_tas .= qq{<tr><td><input type='checkbox'$checked name='$valid[0]' id='$valid[0]' onclick="check_ta('$valid[0]')"><td>$valid[0]<td>$valid[1]<td>$human_class_subjs};	
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM teachers statement: ", $prep_stmt6->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM teachers statement: ", $prep_stmt6->errstr, $/;  
			}

			
		}
			
		my $tas_table = "";

		if ($cntr > 0) {	
			$tas_table = '<table border="1" cellpadding="5%"><thead><th><input type="checkbox" title="Select all on page" name="select_all_teachers" id="select_all_teachers" onclick="check_all_teachers()"><th>Staff ID<th>Name<th>Subjects/Classes Taught</thead>';
			$tas_table .= '<tbody>' . $current_tas. '</tbody></table>';
		}
		else {
			$tas_table .= qq%<em>No teachers have been added to the system yet.</em> To add teachers, go to <a href="/cgi-bin/editteacherlist.cgi">/cgi-bin/editteacherlist.cgi</a>%;
		}
	
		$body .=
qq%
<p><h3>Teachers[<a href="javascript:expand('teachers')"><span id="teachers_show_hide">Show</span></a>]</h3>
<p><div id="teachers_expanded" style="display: none">$tas_table</div>
%;

		#classes
		my %selected_classes;
		my %all_classes = ();
		@all_classes{@classes} = @classes;

		if (exists $profile_vals{"classes"}) {
			my @checked_classes = split/,/,$profile_vals{"classes"};
	
			for my $class (@checked_classes) {
				if (exists $all_classes{$class}) {
					$selected_classes{$class}++;
				}
			}
		}

		my $classes_table = qq%<TABLE><TR><TD><INPUT type="checkbox" onclick="check_all_classes()" title="Check all classes" id="select_all_classes"><TD>*%;

		for my $class (sort {$a cmp $b} keys %all_classes) {
			my $checked = "";

			if (exists $selected_classes{$class}) {
				$checked = " checked";
			}

			$classes_table .= qq%<TR><TD><INPUT type="checkbox"$checked onclick="check_class('$class')" id="$class"><TD>$class%;
		}

		$classes_table .= "</TABLE>";
	
		$body .=
qq%
<p><h3>Classes[<a href="javascript:expand('classes')"><span id="classes_show_hide">Show</span></a>]</h3>
<p><div id="classes_expanded" style="display: none">$classes_table</div>
%;

		#subjects
		my %selected_subjects;
		my %all_subjects = ();
		@all_subjects{@subjects} = @subjects;

		if (exists $profile_vals{"subjects"}) {
			my @checked_subjects = split/,/,$profile_vals{"subjects"};
	
			for my $subject (@checked_subjects) {
				if (exists $all_subjects{$subject}) {
					$selected_subjects{$subject}++;
				}
			}
		}

		my $subjects_table = qq%<TABLE><TR><TD><INPUT type="checkbox" onclick="check_all_subjects()" title="Check all subjects" id="select_all_subjects"><TD>*%;

		for my $subject (sort {$a cmp $b} keys %all_subjects) {
			my $checked = "";

			if (exists $selected_subjects{$subject}) {
				$checked = " checked";
			}

			$subjects_table .= qq%<TR><TD><INPUT type="checkbox"$checked onclick="check_subject('$subject')" id="$subject"><TD>$subject%;
		}

		$subjects_table .= "</TABLE>";	

		$body .=
qq%
<p><h3>Subjects[<a href="javascript:expand('subjects')"><span id="subjects_show_hide">Show</span></a>]</h3>
<p><div id="subjects_expanded" style="display: none">$subjects_table</div>
%;
		#Days of the week
		my $days_week_table = qq%<TABLE><TR><TD><INPUT type="checkbox" onclick="check_all_days()" title="Check all days" id="select_all_days"><TD>*%;

		my @days_week = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday");

		my %selected_days = ();

		if (exists $profile_vals{"days_week"}) {
			my @checked_days = split/,/, lc($profile_vals{"days_week"});
			for my $checked (@checked_days) {
				for my $day (@days_week) {
					if ($checked =~ /^$day$/i) {
						$selected_days{$day}++;
						last;
					}
				}
			}
		}

		for my $day (@days_week) {
			my $checked = "";

			if ( exists $selected_days{$day} ) {
				$checked = " checked";
			}

			$days_week_table .= qq%<TR><TD><INPUT type="checkbox"$checked onclick="check_day('$day')" id="$day"><TD>$day%;
		}

		$days_week_table .= "</TABLE>";
		$body .=
qq%
<p><h3>Days[<a href="javascript:expand('days_week')"><span id="days_week_show_hide">Show</span></a>]</h3>
<p><div id="days_week_expanded" style="display: none">$days_week_table</div>
%;


		#lesson duration
		my $lesson_duration = "";
		if (exists $profile_vals{"lesson_duration"} and $profile_vals{"lesson_duration"} =~ /^\d+$/) {
			$lesson_duration = $profile_vals{"lesson_duration"};
		}

		$body .=
qq%
<p><h3>Lesson Duration[<a href="javascript:expand('lesson_duration')"><span id="lesson_duration_show_hide">Show</span></a>]</h3>
<p><div id="lesson_duration_expanded" style="display: none">
<span id="lesson_duration_error" style="color: red"></span>
<span id="lesson_duration_error_asterisk" style="color: red"></span><LABEL for="lesson_duration_val">How long is each lesson?(in minutes)</LABEL>&nbsp;<INPUT type="text" name="lesson_duration_val" id="lesson_duration_val" value="$lesson_duration" onkeyup="lesson_duration_changed()">
</div>
%;

		my $day_organization_0 = "";
		my $start_lessons_0 = "";

		if (exists $profile_vals{"day_organization_0"}) {
			$day_organization_0 = htmlspecialchars($profile_vals{"day_organization_0"});
		}
		if (exists $profile_vals{"start_lessons_0"}) {	
			$start_lessons_0 = htmlspecialchars($profile_vals{"start_lessons_0"});
		}

		my $num_exceptions = 0;

		my %day_organization_exceptions = ();
		for my $profile_name (keys %profile_vals) {
			#exception_days	
			my $pos = undef;
			if ($profile_name =~ /^exception_days_([0-9]+)/) {	
				$pos = $1;
				if (not exists $day_organization_exceptions{$pos}) {
					$day_organization_exceptions{$pos} = {};	
				}
				${$day_organization_exceptions{$pos}}{"days"} = $profile_vals{$profile_name};
			}
			elsif ($profile_name =~ /^start_lessons_([0-9]+)/) {	
				$pos = $1;
				
				if (not exists $day_organization_exceptions{$pos}) {
					$day_organization_exceptions{$pos} = {};	
				}
				${$day_organization_exceptions{$pos}}{"start"} = $profile_vals{$profile_name};
			}
			elsif ($profile_name =~ /^day_organization_([0-9]+)/) {
				$pos = $1;
			
				if (not exists $day_organization_exceptions{$pos}) {
					$day_organization_exceptions{$pos} = {};	
				}
				${$day_organization_exceptions{$pos}}{"organization"} = $profile_vals{$profile_name};
			}
			if (defined $pos) {
				$num_exceptions = $pos if ($pos > $num_exceptions);
			}
		}

		my $day_organization_exceptions_table = "";
		if (keys %day_organization_exceptions) {
			foreach (keys %day_organization_exceptions) {

				my @days = ();
				my %days_hash = ();

				my $start = undef;
				my $day_org = undef;

				if (exists ${$day_organization_exceptions{$_}}{"days"}) {
					@days = split/,/,${$day_organization_exceptions{$_}}{"days"};
					@days_hash{@days} = @days;
				}
				if (exists ${$day_organization_exceptions{$_}}{"start"}) {
					$start = ${$day_organization_exceptions{$_}}{"start"};
				}
				if (exists ${$day_organization_exceptions{$_}}{"organization"}) {
					$day_org = ${$day_organization_exceptions{$_}}{"organization"};
				}

				if (keys %days_hash and defined $start and defined $day_org) {	
					#add days
					$day_organization_exceptions_table .= qq%<TABLE><TR><TD><LABEL for="exception_days_$_">What days does this exception apply to?</LABEL>&nbsp;<SELECT multiple size="4" name="exception_days_$_" onclick="exception_days_changed($_)">%;
					for my $day_week (@days_week) {
						my $selected = "";
						if ( exists $days_hash{$day_week} ) {
							$selected = " selected";
						}
						$day_organization_exceptions_table .= qq%<OPTION${selected} id="exception_day_${day_week}_${_}" value="$day_week">$day_week</OPTION>%;
					}
					$day_organization_exceptions_table .= "</SELECT>";

					#start	
					$day_organization_exceptions_table .= qq%<TR><TD><LABEL for="start_lessons_$_">Start of Lessons(use 24 hour clock system)</LABEL>&nbsp;<INPUT type="text" id="start_lessons_$_" name="start_lessons_$_" value="$start" onkeyup="start_lesson_changed($_)" size="5" maxlength="5">%;

					#day_org
					$day_organization_exceptions_table .= qq%<TR><TD><LABEL for="day_organization_$_">Day organization</LABEL>&nbsp;<INPUT type="text" id="day_organization_$_" value="$day_org" size="100" onkeyup="day_organization_changed($_)">%;

					$day_organization_exceptions_table .= "</TABLE><HR>";
				}

			}
		}
		#day structure
		$body .=
qq%
<p><h3>Day Organization[<a href="javascript:expand('day_organization')"><span id="day_organization_show_hide">Show</span></a>]</h3>
<p><div id="day_organization_expanded" style="display: none">

<p>Use this section to define how days are organized. The first block of values define how a typical day is structured(e.g weekdays). Using the 'Add Exception' button allows you to define days that are atypical (e.g. weekends). Use <em>{LESSON}</em> to tell Yans where to slot in lessons. Assuming the school day is organized as follows:
<ol>
<li>3 lessons(40 minutes each) in the morning (08:20-10:20)
<li>a 20-minute tea break (10:20-10:40)
<li>3 lessons(10:40-12:40) before lunch (12:40-14:00)
<li>3 more lessons in the afternoon(14:00-16:00); and
<li>another 20-minute tea break.
</ol>
To define this programme, use the following day organization: <strong>{LESSON}{LESSON}{LESSON}Tea Break[20]{LESSON}{LESSON}{LESSON}Lunch[80]{LESSON}{LESSON}{LESSON}Tea Break[20]</strong>. Note the use of square brackets([]) to indicate durations (in minutes).

<HR>

<p><TABLE><TR><TD><LABEL for="start_lessons_0">Start&nbsp;of&nbsp;Lessons(use&nbsp;24&nbsp;hour&nbsp;clock&nbsp;system)</LABEL><TD><INPUT type="text" name="start_lessons_0" id="start_lessons_0" value="$start_lessons_0" onkeyup="start_lesson_changed(0)" size="5" maxlength="5"><TR><TD><LABEL for="day_organization_0">Day&nbsp;organization</LABEL><TD><INPUT type="text" id="day_organization_0" value="$day_organization_0" size="100" onkeyup="day_organization_changed(0)"></TABLE><HR>

<p><input type="button" name="extend_day_org" value="Add Exception" onclick="extend_day_org()">
$day_organization_exceptions_table

<span id="day_organization_exceptions" style="display: block"></span>
</div>
%;
	
		#number of lessons per subject
		$body .=
qq%
<p><h3>Lessons per Subject[<a href="javascript:expand('lessons_per_subject')"><span id="lessons_per_subject_show_hide">Show</span></a>]</h3>
<p><div id="lessons_per_subject_expanded" style="display: none">
<p>Used to specify how much time is sloted to each subject every week. Each subject has a lesson stucture in the form <em>number of lessons x number of periods in lesson [, number of lessons x number of periods in lesson...]</em>. For example, if you wanted a given subject to have 1 double-period lesson and 3 single-period lessons, you should use the following lesson structure: <em>1x2,3x1</em>. NB: the 1<sup>st</sup> value is the number of <em>lessons</em>, the 2<sup>nd</sup> is the number of <em>periods</em> per lesson.
%;
	
		my %lessons_per_subject = ();
		#reserve the the 1st [scalar(@subjects) spaces
		#for the default lesson struct of each subject
		my $num_lesson_structure_exceptions = scalar(@subjects) - 1;

		for my $profile_name_1 (keys %profile_vals) {
			#subject
			my $pos = undef;
			if ($profile_name_1 =~ /^lesson_structure_subject_([0-9]+)/) {
				$pos = $1;	
				if (not exists $lessons_per_subject{$pos}) {
					$lessons_per_subject{$pos} = {};	
				}
				${$lessons_per_subject{$pos}}{"subject"} = $profile_vals{$profile_name_1};
			}
			#structure (proper)
			elsif ($profile_name_1 =~ /^lesson_structure_struct_([0-9]+)/) {
				$pos = $1;	
				if (not exists $lessons_per_subject{$pos}) {
					$lessons_per_subject{$pos} = {};	
				}
				${$lessons_per_subject{$pos}}{"struct"} = $profile_vals{$profile_name_1};
			}
			#classes
			elsif ($profile_name_1 =~ /^lesson_structure_classes_([0-9]+)/) {
				$pos = $1;
				if (not exists $lessons_per_subject{$pos}) {
					$lessons_per_subject{$pos} = {};	
				}
				${$lessons_per_subject{$pos}}{"classes"} = $profile_vals{$profile_name_1};
			}
			if (defined $pos) {
				$num_lesson_structure_exceptions = $pos if ($pos > $num_lesson_structure_exceptions);
			}
		}

		my %lesson_cntr_lookup = ();
		for my $cntr (keys %lessons_per_subject) {
			#this' a PRIMARY lesson structure
			if (not exists ${$lessons_per_subject{$cntr}}{"classes"}) {
				my $subject = ${$lessons_per_subject{$cntr}}{"subject"};
				$lesson_cntr_lookup{$subject} = $cntr;
			}
		}

		$body .= qq%<TABLE border="1"><THEAD><TH>Subject<TH>Lesson Structure</THEAD>%;

		#how do i deal with some missing lesson structures
		#(don't want them to interfere with the $cntr)
		#IDEA: keep a record of these missing lesson structures
		#BETTER (SIMPLER): u know all the $cntrs, store them in a hash 
		#delete the ones you see, pick any of the remaining ones for future
		#allocs. Order doesn't matter, all will be settled when the data is proc'd	
		my %reserved_cntrs = ();
		my $cnt = 0;

		@reserved_cntrs{0..(scalar(@subjects) - 1)} = 0..(scalar(@subjects) - 1);

		for my $subject_0 (@subjects) {
	
			my $lesson_struct = "";
			if ( exists $lesson_cntr_lookup{$subject_0} ) {

				$cnt = $lesson_cntr_lookup{$subject_0};
				delete $reserved_cntrs{$cnt};

				if (exists ${$lessons_per_subject{$cnt}}{"struct"}) { 
					$lesson_struct = ${$lessons_per_subject{$cnt}}{"struct"};	
				}
			}
			#pick any cntr @ random
			else {
				$cnt = (keys %reserved_cntrs)[0];
				delete $reserved_cntrs{$cnt};
			}

			$body .=
qq%<TR><TD><span id="error_lesson_structure_$cnt" style="color: red"></span><INPUT readonly type="text" id="lesson_structure_subject_$cnt" value="$subject_0"><TD><INPUT type="text" name="lesson_structure_struct_$cnt" id="lesson_structure_struct_$cnt" onkeyup="lesson_structure_changed($cnt)" value="$lesson_struct">%;
		}

		$body .= "</TABLE>";
		$body .= qq%<p><INPUT type="button" name="extend_lessons_per_subject" value="Add Exception" onclick="extend_lessons_per_subject()">%;

		#pre_existing lesson structure exceptions
		$body .= qq%<span id="lesson_structure_exceptions" style="display: block"></span>%;

		if (keys %lessons_per_subject) {
			$body .= "<HR>";
			for my $cnt (keys %lessons_per_subject) {
				next unless (exists ${$lessons_per_subject{$cnt}}{"classes"}); 
				$body .= "<P><TABLE>";
				#subject 
				my $subj = ${$lessons_per_subject{$cnt}}{"subject"};
				$body .= qq%<TR><TD><LABEL for="lesson_structure_subject_$cnt">Subject</LABEL><TD><INPUT readonly type="text" value="$subj" id="lesson_structure_subject_$cnt" name="lesson_structure_subject_$cnt">%;

				#classes
				my %classes_hash;
				
				my @selected_classes = split/,/, ${$lessons_per_subject{$cnt}}{"classes"};
				@classes_hash{@selected_classes} = @selected_classes;

				$body .= qq%<TR><TD><LABEL>Classes</LABEL><TD>%;

				for my $class (sort {$a cmp $b} @classes) {
					my $checked = "";
					if (exists $classes_hash{$class}) {
						$checked = " checked";
					}
					$body .= qq%<INPUT$checked id="lesson_structure_${class}_${cnt}" name="lesson_structure_${class}_${cnt}" type="checkbox" onclick="lesson_structure_changed($cnt)">&nbsp;$class&nbsp;&nbsp;&nbsp;%;
				}

				#structure
				my $struct = ${$lessons_per_subject{$cnt}}{"struct"};
				$body .= qq%<TR><TD><span id="error_lesson_structure_$cnt" style="color: red"></span><LABEL for="lesson_structure_struct_$cnt">Lesson structure</LABEL><TD><INPUT type="text" name="lesson_structure_struct_$cnt" id="lesson_structure_struct_$cnt" onkeyup="lesson_structure_changed($cnt)" value="$struct">%;

				$body .= "</TABLE><HR>";
			}
		}

		#lessons_structure exceptions span
		$body .= qq%<span id="lesson_structure_exceptions" style="display: block"></span>%;
		$body .= "</div>";

		#lesson associations(simultaneous)
		$body .=
qq%
<p><h3>Lesson associations[<a href="javascript:expand('lesson_associations')"><span id="lesson_associations_show_hide">Show</span></a>]</h3>
<p><div id="lesson_associations_expanded" style="display: none">
<p>Allows you to define how lessons are related e.g. lessons that should never be scheduled simultaneously.
%;

		my $num_lesson_associations = 0;
		#simultaneous
		my %simultaneous;
		my %mutually_exclusive;
		my %occasional_joint;
		#consecutive
		my %consecutive;
		my %non_consecutive;

		for my $profile_name_2 (keys %profile_vals) {
			my $pos = undef;
			if ($profile_name_2 =~ /^lesson_associations_simultaneous_([0-9]+)$/) {
				$pos = $1;
				$simultaneous{$pos} = $profile_vals{$profile_name_2};
			}

			elsif ($profile_name_2 =~ /^lesson_associations_mut_ex_([0-9]+)$/) {
				$pos = $1;
				$mutually_exclusive{$pos} = $profile_vals{$profile_name_2};
			}

			elsif ($profile_name_2 =~ /^lesson_associations_occasional_joint_lessons_([0-9]+)$/) {
				$pos = $1;
				if (not exists $occasional_joint{$pos}) {
					$occasional_joint{$pos} = {};
				}
				${$occasional_joint{$pos}}{"lessons"} = $profile_vals{$profile_name_2};
			}

			elsif (	$profile_name_2 =~ /^lesson_associations_occasional_joint_format_([0-9]+)$/) {
				$pos = $1;
				if (not exists $occasional_joint{$pos}) {
					$occasional_joint{$pos} = {};
				}
				${$occasional_joint{$pos}}{"format"} = $profile_vals{$profile_name_2};
			}
=pod
			elsif (	$profile_name_2 =~ /^lesson_associations_always_consecutive_([0-9]+)$/) {
				$pos = $1;
				$consecutive{$pos} = $profile_vals{$profile_name_2};
			}
=cut
			elsif (	$profile_name_2 =~ /^lesson_associations_consecutive_([0-9]+)$/) {
				$pos = $1;
				if (not exists $non_consecutive{$pos}) {
					$non_consecutive{$pos} = {};
				}
				${$non_consecutive{$pos}}{"lessons"} = $profile_vals{$profile_name_2};
			}
=pod
			elsif (	$profile_name_2 =~ /^lesson_associations_never_consecutive_gap_([0-9]+)$/) {
				$pos = $1;
				if (not exists $non_consecutive{$pos}) {
					$non_consecutive{$pos} = {};
				}
				${$non_consecutive{$pos}}{"gap"} = $profile_vals{$profile_name_2};
			}
=cut

			if (defined $pos) {
				$num_lesson_associations = $pos if ($pos > $num_lesson_associations);
			}
		}

		
		#simulatenous
		$body .=
qq%<h4>Lessons always held simultaneously</h4>
<UL style="list-style-type: none">
%;

		for my $simult (keys %simultaneous) {
			my @simultaneous_lessons = split/,/, $simultaneous{$simult};
			for my $lesson (@simultaneous_lessons) {
				$body .= 
qq%
<LI><LABEL id="label_simultaneous_lesson_associations_${simult}_${lesson}">$lesson&nbsp;&nbsp;</LABEL><INPUT type="button" value="Remove" onclick="remove_simultaneous_lesson_association($simult, '$lesson')" id="button_simultaneous_lesson_associations_${simult}_${lesson}">
%;
			}
			#add lesson to this group
			$body .= qq%<span id="add_simultaneous_lesson_associations_$simult"></span>%;
			$body .= qq%<LI><INPUT type="button" value="Add" onclick="show_add_simultaneous_lesson_association($simult)">%;
			$body .= "<HR>";
		}

		#add new group
		$body .= 
qq%
<span id="create_simultaneous_lesson_associations"></span>
<LI><INPUT type="button" value="Create New Association" onclick="show_create_simultaneous_lesson_association()">
%;
		$body .= "</UL><HR><HR>";

		#mutually exclusive 
		$body .=
qq%<h4>Lessons never held simultaneously</h4>
<UL style="list-style-type: none">
%;

		for my $simult_1 (keys %mutually_exclusive) {
			my @mut_ex_lessons = split/,/, $mutually_exclusive{$simult_1};
			for my $lesson (@mut_ex_lessons) {
				$body .=
qq%
<LI><LABEL id="label_mut_ex_lesson_associations_${simult_1}_${lesson}">$lesson&nbsp;&nbsp;</LABEL><INPUT type="button" value="Remove" onclick="remove_mut_ex_lesson_association($simult_1, '$lesson')" id="button_mut_ex_lesson_associations_${simult_1}_${lesson}">
%;
			}
			#add lesson to this group
			$body .= qq%<span id="add_mut_ex_lesson_associations_$simult_1"></span>%;
			$body .= qq%<LI><INPUT type="button" value="Add" onclick="show_add_mut_ex_lesson_association($simult_1)">%;
			$body .= "<HR>";
		}

		#add new group
		$body .= 
qq%
<span id="create_mut_ex_lesson_associations"></span>
<LI><INPUT type="button" value="Create New Association" onclick="show_create_mut_ex_lesson_association()">
%;
		$body .= "</UL><HR><HR>";

		#occasional joint
		$body .=
qq%<h4>Lessons occasionally held simultaneously</h4>
The number of joint lessons is specified in the form <em>number of lessons x number of periods in lesson [, number of lessons x number of periods in lesson...]</em>. For example, if you wanted to have 1 double-period joint lesson and 3 single-period joint lessons, you should enter the following: <em>1x2,3x1</em>. NB: the 1<sup>st</sup> value is the number of <em>lessons</em>, the 2<sup>nd</sup> is the number of <em>periods</em> per lesson.
<UL style="list-style-type: none">
%;

		for my $simult_2 (keys %occasional_joint) {
			my $format = ${$occasional_joint{$simult_2}}{"format"};

			$body .= qq%<LI><span style="color: red" id="error_occasional_joint_lesson_associations_format_$simult_2"></span><LABEL>Number of Joint Lessons</LABEL>&nbsp;&nbsp;<INPUT type="text" value="$format" id="occasional_joint_lessons_format_$simult_2" onkeyup="occasional_joint_lesson_format_changed($simult_2)">%;

			my @occasional_joint_lessons = split/,/,${$occasional_joint{$simult_2}}{"lessons"};
			for my $lesson (@occasional_joint_lessons) {
				$body .=
qq%
<LI><LABEL id="label_occasional_joint_lesson_associations_${simult_2}_${lesson}">$lesson&nbsp;&nbsp;</LABEL><INPUT type="button" value="Remove" onclick="remove_occasional_joint_lesson_association($simult_2, '$lesson')" id="button_occasional_joint_lesson_associations_${simult_2}_${lesson}">
%;
			}

			#add lesson to this group
			$body .= qq%<span id="add_occasional_joint_lesson_associations_$simult_2"></span>%;
			$body .= qq%<LI><INPUT type="button" value="Add" onclick="show_add_occasional_joint_lesson_association($simult_2)">%;
			$body .= "<HR>";
		}

		#add new group
		$body .= 
qq%
<span id="create_occasional_joint_lesson_associations"></span>
<LI><INPUT type="button" value="Create New Association" onclick="show_create_occasional_joint_lesson_association()">
%;
		$body .= "</UL><HR><HR>";

		#never consecutive
		$body .=
qq%<h4>Lessons never held consecutively</h4>
<UL style="list-style-type: none">
%;

		for my $simult_3 (keys %non_consecutive) {
			my @non_consecutive_lessons = split/,/, $non_consecutive{$simult_3}->{"lessons"};
			for my $lesson (@non_consecutive_lessons) {
				$body .= 
qq%
<LI><LABEL id="label_consecutive_lesson_associations_${simult_3}_${lesson}">$lesson&nbsp;&nbsp;</LABEL><INPUT type="button" value="Remove" onclick="remove_consecutive_lesson_association($simult_3, '$lesson')" id="button_consecutive_lesson_associations_${simult_3}_${lesson}">
%;
			}
			#add lesson to this group
			$body .= qq%<span id="add_consecutive_lesson_associations_$simult_3"></span>%;
			$body .= qq%<LI><INPUT type="button" value="Add" onclick="show_add_consecutive_lesson_association($simult_3)">%;
			$body .= "<HR>";
		}

		#add new group
		$body .= 
qq%
<span id="create_consecutive_lesson_associations"></span>
<LI><INPUT type="button" value="Create New Association" onclick="show_create_consecutive_lesson_association()">
%;

		$body .= "</UL><HR><HR>";

		$body .= "</div>";

		#fixed scheduling
		my $num_fixed_scheduling = 0;

		my %fixed_scheduling;
		for my $profile_name_3 (keys %profile_vals) {
			my $cnt;
			if ($profile_name_3 =~ /^fixed_scheduling_lessons_([0-9]+)$/) {
				$cnt = $1;
				${$fixed_scheduling{$cnt}}{"lessons"} = $profile_vals{$profile_name_3};
			}

			elsif ($profile_name_3 =~ /^fixed_scheduling_periods_([0-9]+)$/) {
				$cnt = $1;
				${$fixed_scheduling{$cnt}}{"periods"} = $profile_vals{$profile_name_3};
			}

			if (defined($cnt)) {
				$num_fixed_scheduling = $cnt if ($cnt > $num_fixed_scheduling);
			}
		}
		
		$body .=
qq%
<p><h3>Lessons with Fixed Scheduling[<a href="javascript:expand('fixed_scheduling')"><span id="fixed_scheduling_show_hide">Show</span></a>]</h3>
<p><div id="fixed_scheduling_expanded" style="display: none">
<p>Use this section to define lessons that can only occur at certain times. For instance, you can specify that P.E will only occur before lunch or before tea breaks on Mondays, Wednesdays and Fridays by checking the appropriate days and entering the 2 periods in the 'periods' box (e.g. '3,5' with no quotes).
%;

		for my $cnt_4 (keys %fixed_scheduling) {

			#Lessons
			$body .= "<h4>Lessons</h4>";
			my @lessons = split/,/,${$fixed_scheduling{$cnt_4}}{"lessons"};
			$body .= qq!<p><UL style="list-style-type: none">!;
			for my $lesson (@lessons) {
				$body .= qq!<LI><LABEL id="label_fixed_scheduling_lesson_${cnt_4}_${lesson}">$lesson</LABEL>&nbsp;<INPUT type="button" value="Remove" onclick="remove_fixed_scheduling_lesson($cnt_4,'$lesson')" id="button_fixed_scheduling_lesson_${cnt_4}_${lesson}">!;
			}			

			#add lesson to this fixed schedule 
			$body .= qq%<span id="box_add_fixed_scheduling_lesson_$cnt_4"></span>%;
			$body .= qq%<LI><INPUT type="button" value="Add" onclick="show_add_fixed_scheduling_lesson($cnt_4)">%;

			$body .= "</UL>";
			
			#period
			$body .= "<h4>Periods</h4>";
			my @periods = split/;/,${$fixed_scheduling{$cnt_4}}{"periods"};	
	
			$body .= qq!<p><TABLE border="1"><THEAD><TH><INPUT type="checkbox" onclick="check_all_fixed_scheduling_days($cnt_4)" id="checkbox_check_all_fixed_scheduling_days_$cnt_4"><TH>Day<TH>Periods</THEAD><TBODY>!;
			for my $day (@days_week) {
				my $checked = " ";
				my $set_periods = "";
				my $style_color =  qq! style="color: grey"!;

				for my $period (@periods) {
					if ($period =~ /^$day\(([0-9,]+)\)$/) {
						$set_periods = $1;
						$checked = " checked ";
						$style_color = "";
						last;
					}
				}
				$body .= qq!<TR><TD><INPUT type="checkbox"${checked}id="checkbox_fixed_scheduling_day_${cnt_4}_$day" onclick="checked_fixed_scheduling_day($cnt_4,'$day')"><TD><LABEL id="label_fixed_scheduling_day_${cnt_4}_${day}"${style_color}>$day</LABEL><TD><span id="error_periods_fixed_scheduling_day_${cnt_4}_$day" style="color: red"></span><INPUT type="text" value="$set_periods" id="periods_fixed_scheduling_day_${cnt_4}_$day" onkeyup="changed_fixed_scheduling_periods($cnt_4)">!;
			}

			$body .= "</TBODY></TABLE><HR>"; 
		}

		$body .=
qq%
<span id="extend_fixed_scheduling" style="display: block"></span>
<P><INPUT type="button" value="Create New Fixed Schedule" onclick="show_create_fixed_scheduling()">
</div>
%;

		#teacher's free time
		my $num_free_afternoons = 0;
		my $num_free_mornings = 0;
		my $max_consecutive_lessons = 3;

		#free afternoons
		if (exists $profile_vals{"teachers_number_free_afternoons"} and $profile_vals{"teachers_number_free_afternoons"} =~ /^\d+$/) {
			$num_free_afternoons = $profile_vals{"teachers_number_free_afternoons"};
		}
		#free mornings
		if (exists $profile_vals{"teachers_number_free_mornings"} and $profile_vals{"teachers_number_free_mornings"} =~ /^\d+$/) {
			$num_free_mornings = $profile_vals{"teachers_number_free_mornings"};
		}

		if (exists $profile_vals{"teachers_maximum_consecutive_lessons"} and $profile_vals{"teachers_maximum_consecutive_lessons"} =~ /^\d+$/) {
			$max_consecutive_lessons = $profile_vals{"teachers_maximum_consecutive_lessons"};
		}

		
		$body .=
qq%
<p><h3>Teachers' Free Time[<a href="javascript:expand('teachers_free_time')"><span id="teachers_free_time_show_hide">Show</span></a>]</h3>
<p><div id="teachers_free_time_expanded" style="display: none">
<UL style="list-style-type: none">
<LI><LABEL>Number of Free Afternoons</LABEL>&nbsp;<span id="error_teachers_number_free_afternoons" style="color: red"></span><INPUT type="text" value="$num_free_afternoons" id="teachers_number_free_afternoons" onkeyup="changed_teachers_number_free_afternoons()">

<LI><LABEL>Number of Free Mornings</LABEL>&nbsp;<span id="error_teachers_number_free_mornings" style="color: red"></span><INPUT type="text" value="$num_free_mornings" id="teachers_number_free_mornings" onkeyup="changed_teachers_number_free_mornings()">

<LI><LABEL>Maximum Number of Consecutive Lessons</LABEL>&nbsp;<span id="error_teachers_maximum_consecutive_lessons" style="color: red"></span><INPUT type="text" value="$max_consecutive_lessons" id="teachers_maximum_consecutive_lessons" onkeyup="changed_teachers_maximum_consecutive_lessons()">
</UL>
</div>
%;

		my $maximum_number_doubles = 2;
		if (exists $profile_vals{"maximum_number_doubles"} and $profile_vals{"maximum_number_doubles"} =~ /^\d+$/) {
			$maximum_number_doubles = $profile_vals{"maximum_number_doubles"};
		}

		$body .= 
qq%
<p><h3>Student's Free Time[<a href="javascript:expand('students_free_time')"><span id="students_free_time_show_hide">Show</span></a>]</h3>
<p><div id="students_free_time_expanded" style="display: none">
<P><LABEL>Daily Maximum Number of Double Lessons</LABEL>&nbsp;<span id="error_maximum_number_doubles" style="color: red"></span><INPUT type="text" value="$maximum_number_doubles" id="maximum_number_doubles" onkeyup="changed_maximum_number_doubles()">
</div>
%;

		#save button
		$body .= qq%<p><INPUT disabled type="button" value="Save Changes" id="save_changes" onclick="save()">%;

		#tas_ids;
		my $tas_ids_js_str = join(", ", @tas_ids);
		my $pre_selected_tas = join(", ", keys %selected_tas);

		#classes
		my @quoted_selected_classes = ();

		for my $selected_class (keys %selected_classes) {
			push @quoted_selected_classes, qq!"$selected_class"!;
		}

		my $pre_selected_classes = join(", ", @quoted_selected_classes);
		my $all_classes_js_str = "";
		if (keys %all_classes) {
			$all_classes_js_str = qq%"% . join(qq%", "%, sort {$a cmp $b} keys %all_classes). qq%"%;
		}

		#subjects
		my @quoted_selected_subjects = ();
		
		for my $selected_subject (keys %selected_subjects) {
			push @quoted_selected_subjects, qq!"$selected_subject"!;
		}

		my $pre_selected_subjects = join(", ", @quoted_selected_subjects);
		my $all_subjects_js_str = "";
		if (keys %all_subjects) {
			$all_subjects_js_str = qq%"% . join(qq%", "%, keys %all_subjects). qq%"%;
		}

		#days
		my @quoted_selected_days = ();

		for my $selected_day (keys %selected_days) {
			push @quoted_selected_days, $selected_day;
		}

		my $pre_selected_days = join(", ", keys @quoted_selected_days);
		my $all_days_js_str = "";
		if (@days_week) {
			$all_days_js_str = qq%"% . join(qq%", "%, @days_week). qq%"%;
		}
	
		#exceptions

		#lesson associations
		#simultaneous
		my @simult_lessons_js_bts = ();
	
		for my $cnt_0 (keys %simultaneous) {
			push @simult_lessons_js_bts, qq%{name: $cnt_0, value: "$simultaneous{$cnt_0}"}%;
		}
		my $simult_lessons_js_str = join(", ", @simult_lessons_js_bts);
	
		#mut_ex
		my @mut_ex_lessons_js_bts = ();
		for my $cnt_1 (keys %mutually_exclusive) {
			push @mut_ex_lessons_js_bts, qq%{name: $cnt_1, value: "$mutually_exclusive{$cnt_1}"}%;
		}
		my $mut_ex_js_str = join(", ", @mut_ex_lessons_js_bts);

		#occasional joint
		my @occasional_joint_lessons_js_bts = ();
		for my $cnt_2 (keys %occasional_joint) {
			push @occasional_joint_lessons_js_bts, qq%{name: $cnt_2, format: "${$occasional_joint{$cnt_2}}{"format"}", lessons: "${$occasional_joint{$cnt_2}}{"lessons"}"}%;
		}

		my $occasional_joint_js_str = join(", ", @occasional_joint_lessons_js_bts);

		#always consecutive
		my @consecutive_lessons_js_bts = ();
		for my $cnt_1 (keys %non_consecutive) {
			push @consecutive_lessons_js_bts, qq%{name: $cnt_1, value: "$non_consecutive{$cnt_1}->{"lessons"}"}%;
		}
		my $consecutive_js_str = join(", ", @consecutive_lessons_js_bts);


		#lessons with fixed scheduling		
		my @fixed_scheduling_lessons = ();
		for my $cnt_3 (keys %fixed_scheduling) {
			push @fixed_scheduling_lessons, qq%{name: $cnt_3, lessons: "${$fixed_scheduling{$cnt_3}}{"lessons"}", periods: "${$fixed_scheduling{$cnt_3}}{"periods"}"}%;
		}

		my $fixed_scheduling_js_str = join(", ", @fixed_scheduling_lessons);

		$js .=
qq%
<SCRIPT type="text/javascript">

var old_content = "";

var all_tas = [$tas_ids_js_str];
var all_classes = [$all_classes_js_str];
var all_subjects = [$all_subjects_js_str];
var all_days = [$all_days_js_str];

var simult_lessons = [$simult_lessons_js_str];
var mut_ex_lessons = [$mut_ex_js_str];
var occasional_joint_lessons = [$occasional_joint_js_str];
var consecutive_lessons = [$consecutive_js_str];

var fixed_scheduling_lessons = [$fixed_scheduling_js_str];

var simult_add_cnts = [];
var mut_ex_add_cnts = [];
var occasional_joint_add_cnts = [];
var consecutive_add_cnts = [];

var fixed_scheduling_add_cnts = [];

var num_exceptions = $num_exceptions;
var num_lesson_structure_exceptions = $num_lesson_structure_exceptions;
var num_lesson_associations = $num_lesson_associations;

var num_fixed_scheduling = $num_fixed_scheduling;

var expanded = [ {name: "teachers", value: false}, {name: "classes", value: false}, {name: "subjects", value: false}, {name: "days_week", value: false}, {name: "lesson_duration", value: false}, {name: "day_organization", value: false}, {name: "lessons_per_subject", value: false}, {name: "lesson_associations", value: false}, {name: "fixed_scheduling", value: false}, {name: "teachers_free_time", value: false}, {name: "students_free_time", value: false} ];

var changed = [];
var changed_flag = 0;

var selected_teachers = [$pre_selected_tas];
var selected_classes = [$pre_selected_classes];
var selected_subjects = [$pre_selected_subjects];
var selected_days = [$pre_selected_days];

var getter_functions = [];

//functions to retrieve values in decent
//format & reset values

getter_functions["teachers"] = function() {

	var selected_tas_str = selected_teachers.join(",");
	selected_teachers = [];

	return selected_tas_str;
}

getter_functions["classes"] = function() {

	var selected_classes_str = selected_classes.join(",");
	selected_classes = [];
	
	return selected_classes_str;
}

getter_functions["subjects"] = function() {

	var selected_subjects_str = selected_subjects.join(",");
	selected_subjects = [];
	
	return selected_subjects_str;
}

getter_functions["days_week"] = function() {

	var selected_days_str = selected_days.join(",");
	selected_days = [];
	
	return selected_days_str;
}

getter_functions["lesson_duration"] = function() {

	var lesson_duration_value = document.getElementById("lesson_duration_val").value;
	return lesson_duration_value;
}


function expand(id) {
	for (var id_iter in expanded) {

		if (expanded[id_iter].name == id) {
			//now hide
			if ( expanded[id_iter].value ) {
				//Show/Hide button
				document.getElementById(id + "_show_hide").innerHTML = "Show";
				//innerHTML
				document.getElementById(id + "_expanded").style.display = "none";
				expanded[id_iter].value = false;
			}
			else {
				//Show/Hide button
				document.getElementById(id + "_show_hide").innerHTML = "Hide";
				//innerHTML
				document.getElementById(id + "_expanded").style.display = "block";
			
	document.getElementById(id + "_expanded").style.margin = "2em";	
				expanded[id_iter].value = true;
			}
			break;
		}
	}
}

function check_all_teachers() {
	//add to changed
	changed["teachers"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;
	var all_checked = document.getElementById("select_all_teachers").checked;
	if (all_checked) {
		selected_teachers = [];
		for (var ta in all_tas) {
			selected_teachers.push(all_tas[ta]);
		}
	}
	else {
		selected_teachers = [];	
	}

	for (var i = 0; i < all_tas.length; i++) {
		document.getElementById(all_tas[i]).checked = all_checked;
	}
}

function check_ta(sup_id) {
	//add to changed values
	changed["teachers"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;

	if (document.getElementById(sup_id) != null) {
		if (document.getElementById(sup_id).checked) {
			selected_teachers.push(sup_id);
		}
		else {
			for (var i = 0; i < selected_teachers.length; i++) {
				if (selected_teachers[i] === sup_id) {
					selected_teachers.splice(i, 1);
					break;
				}
			}
		}
	}
}

function check_all_classes() {
	//add to changed
	changed["classes"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;
	var all_checked = document.getElementById("select_all_classes").checked;
	if (all_checked) {
		selected_classes = [];
		for (var class_ in all_classes) {
			selected_classes.push(all_classes[class_]);
		}
	}
	else {
		selected_classes = [];	
	}

	for (var i = 0; i < all_classes.length; i++) {
		document.getElementById(all_classes[i]).checked = all_checked;
	}
}

function check_class(class_) {
	changed["classes"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;

	if (document.getElementById(class_) != null) {
		if (document.getElementById(class_).checked) {
			selected_classes.push(class_);
		}
		else {
			for (var i = 0; i < selected_classes.length; i++) {
				if (selected_classes[i] === class_) {
					selected_classes.splice(i, 1);
					break;
				}
			}
		}
	}
}

function check_all_subjects() {
	//add to changed
	changed["subjects"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;
	var all_checked = document.getElementById("select_all_subjects").checked;
	if (all_checked) {
		selected_subjects = [];
		for (var subject in all_subjects) {
			selected_subjects.push(all_subjects[subject]);
		}
	}
	else {
		selected_subjects = [];	
	}

	for (var i = 0; i < all_subjects.length; i++) {
		document.getElementById(all_subjects[i]).checked = all_checked;
	}
}

function check_subject(subject) {
	changed["subjects"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;

	if (document.getElementById(subject) != null) {
		if (document.getElementById(subject).checked) {
			selected_subjects.push(subject);
		}
		else {
			for (var i = 0; i < selected_subjects.length; i++) {
				if (selected_subjects[i] === subject) {
					selected_subjects.splice(i, 1);
					break;
				}
			}
		}
	}
}

function check_all_days() {
	//add to changed
	changed["days_week"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;
	var all_checked = document.getElementById("select_all_days").checked;
	if (all_checked) {
		selected_days = [];
		for (var day in all_days) {
			selected_days.push(all_days[day]);
		}
	}
	else {
		selected_days = [];	
	}

	for (var i = 0; i < all_days.length; i++) {
		document.getElementById(all_days[i]).checked = all_checked;
	}
}


function check_day(day) {
	changed["days_week"] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;

	if (document.getElementById(day) != null) {
		if (document.getElementById(day).checked) {
			selected_days.push(day);
		}
		else {
			for (var i = 0; i < selected_days.length; i++) {
				if (selected_days[i] === day) {
					selected_days.splice(i, 1);
					break;
				}
			}
		}
	}
}

function lesson_duration_changed() {
	var new_val = document.getElementById("lesson_duration_val").value;
	var re = /^[0-9]{1,}\$/;

	if (new_val.match(re) ) {
		document.getElementById("lesson_duration_error_asterisk").innerHTML = "";
		document.getElementById("lesson_duration_error").innerHTML = "";
		changed["lesson_duration"] = true;
		changed_flag++;
		document.getElementById("save_changes").disabled = false;
	}
	else {
		changed["lesson_duration"] = false;
		changed_flag--;

		document.getElementById("lesson_duration_error_asterisk").innerHTML = "*";
		document.getElementById("lesson_duration_error").innerHTML = "Invalid lesson duration: must be a number.<br>";
	}
}

function start_lesson_changed(lesson_cnt) {
	changed["start_lessons_" + lesson_cnt] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;

	getter_functions["start_lessons_" + lesson_cnt] = function() {	
		var val = document.getElementById("start_lessons_" + lesson_cnt).value;
		return val;
	}
}

function day_organization_changed(org_cnt) {
	changed["day_organization_" + org_cnt] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;

	getter_functions["day_organization_" + org_cnt] = function() {	
		var val = document.getElementById("day_organization_" + org_cnt).value;
		return val;
	}
}

function exception_days_changed(days_cnt) {
	changed["exception_days_" + days_cnt] = true;
	changed_flag++;

	document.getElementById("save_changes").disabled = false;

	getter_functions["exception_days_" + days_cnt] = function() {
		var selection = new Array();
		var days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];	
		for ( var i = 0; i < days.length; i++ ) {	
			if (document.getElementById("exception_day_" + days[i] + "_" + days_cnt).selected) {
				selection.push(days[i]);
			}
		}
		return selection.join(",");
	}
}

function extend_day_org() {
	
	num_exceptions++;

	var new_exts = '<UL style="list-style-type: none">';

	new_exts += '<LI><P><LABEL for="exception_days_' + num_exceptions + '">What days does this exception apply to?</LABEL>&nbsp;';

	new_exts += '<SELECT multiple size="4" name="exception_days_' + num_exceptions + '" onclick="exception_days_changed(' + num_exceptions + ')">';

	new_exts += '<OPTION id="exception_day_Monday_' + num_exceptions + '" value="Monday">Monday</OPTION>';
	new_exts += '<OPTION id="exception_day_Tuesday_' + num_exceptions + '" value="Tuesday">Tuesday</OPTION>';
	new_exts += '<OPTION id="exception_day_Wednesday_' + num_exceptions + '" value="Wednesday">Wednesday</OPTION>';
	new_exts += '<OPTION id="exception_day_Thursday_' + num_exceptions + '" value="Thursday">Thursday</OPTION>';
	new_exts += '<OPTION id="exception_day_Friday_' + num_exceptions + '" value="Friday">Friday</OPTION>';
	new_exts += '<OPTION id="exception_day_Saturday_' + num_exceptions + '" value="Saturday">Saturday</OPTION>';
	new_exts += '<OPTION id="exception_day_Sunday_' + num_exceptions + '" value="Sunday">Sunday</OPTION>';	
		
	new_exts += '</SELECT>';

	new_exts += '<LI><P><LABEL for="start_lessons_' + num_exceptions + '">Start&nbsp;of&nbsp;Lessons(use&nbsp;24&nbsp;hour&nbsp;clock&nbsp;system)</LABEL>&nbsp;';
	new_exts += '<INPUT type="text" name="start_lessons_' + num_exceptions + '" id="start_lessons_' + num_exceptions + '" value="" onkeyup="start_lesson_changed(' + num_exceptions + ')" size="5" maxlength="5">';
	new_exts += '<LI><P><LABEL for="day_organization_' + num_exceptions +'">Day&nbsp;organization</LABEL>&nbsp;';
	new_exts += '<INPUT type="text" id="day_organization_' + num_exceptions + '" value="" size="100" onkeyup="day_organization_changed(' + num_exceptions + ')">';

	new_exts += '</UL>';	
	new_exts += '<HR>';

	var new_exts_span = document.createElement("span");
	new_exts_span.innerHTML = new_exts;

	document.getElementById("day_organization_exceptions").appendChild(new_exts_span);
}


function lesson_structure_changed(struc_cntr) {
	//lesson structure
	
	var new_structure = document.getElementById("lesson_structure_struct_" + struc_cntr).value;
	var lesson_struct_bts = new_structure.split(/\\s*,\\s*/);

	var match = true;
	var lesson_struct_re = /^[0-9]*\\s*x?\\s*[0-9]*\$/;

	for (var i = 0; i < lesson_struct_bts.length; i++) {
		if (!lesson_struct_bts[i].match(lesson_struct_re)) {
			match = false;
			break;	
		}
	}
	//clear error msgs etc
	if (match) {
		document.getElementById("error_lesson_structure_" + struc_cntr).innerHTML = "";

		var subjects = "";

		var type = (document.getElementById("lesson_structure_subject_" + struc_cntr).type).toLowerCase();
		//there's only 1 subject; it's in a text field
		if (type == "text") {
			subjects = document.getElementById("lesson_structure_subject_" + struc_cntr).value;
		}
		//there're multiple subjects in a select field
		else {
			var subjs_array = new Array();
			for (var j = 0; j < all_subjects.length; j++) {
				if ( document.getElementById("lesson_structure_" + all_subjects[j] + "_" + struc_cntr).selected ) {
					subjs_array.push(all_subjects[j]);
				}
			}
			subjects = subjs_array.join(",");
		}

		if ( subjects.length > 0 ) {
			if (type == "text") {
				changed["lesson_structure_struct_" + struc_cntr] = true;	
				changed["lesson_structure_subject_" + struc_cntr] = true;
				changed_flag++;

				document.getElementById("save_changes").disabled = false;

				getter_functions["lesson_structure_struct_" + struc_cntr] = function() {	
					//to deal with cancel
					changed["lesson_structure_struct_" + struc_cntr] = false;		
					return new_structure;
				}

				getter_functions["lesson_structure_subject_" + struc_cntr] = function() {
					changed["lesson_structure_subject_" + struc_cntr] = false;
					return subjects;
				}
				
			}
			//classes
			else {
				var classes_arr = new Array();
				for (var k = 0; k < all_classes.length; k++) {
					if (document.getElementById("lesson_structure_" + all_classes[k] + "_" + struc_cntr).checked) {
						classes_arr.push(all_classes[k]);
					}
				}
				if (classes_arr.length > 0) {
					var classes = classes_arr.join(",");
						
					changed["lesson_structure_struct_" + struc_cntr] = true;	
					changed["lesson_structure_subject_" + struc_cntr] = true;	
					changed["lesson_structure_classes_" + struc_cntr] = true;
					changed_flag++;

					document.getElementById("save_changes").disabled = false;

					getter_functions["lesson_structure_struct_" + struc_cntr] = function() {	
						changed["lesson_structure_struct_" + struc_cntr] = false;	
						return new_structure;
					}

					getter_functions["lesson_structure_subject_" + struc_cntr] = function() {
						changed["lesson_structure_subject_" + struc_cntr] = false;
						return subjects;
					}

					getter_functions["lesson_structure_classes_" + struc_cntr] = function() {
						changed["lesson_structure_classes_" + struc_cntr] = false;
						return classes;
					}
				}
				else {
					changed["lesson_structure_struct_" + struc_cntr] = false;
					changed["lesson_structure_subject_" + struc_cntr] = false;
					changed["lesson_structure_classes_" + struc_cntr] = false;
				}
			}

		}
		else {
			changed["lesson_structure_struct_" + struc_cntr] = false;
			changed["lesson_structure_subject_" + struc_cntr] = false;
			changed["lesson_structure_classes_" + struc_cntr] = false;
		}
	}

	//set error msgs etc
	else {
		document.getElementById("error_lesson_structure_" + struc_cntr).innerHTML = "*";
		changed["lesson_structure_struct_" + struc_cntr] = false;
		changed["lesson_structure_subject_" + struc_cntr] = false;
		changed["lesson_structure_classes_" + struc_cntr] = false;
	}
}

function extend_lessons_per_subject() {
	num_lesson_structure_exceptions++;

	var new_exts = '<P><TABLE>';
	new_exts += '<TR><TD>';
	new_exts += '<TR><TD><LABEL for="lesson_structure_subject_' + num_lesson_structure_exceptions + '">Subject</LABEL><TD><SELECT name="lesson_structure_subject_' + num_lesson_structure_exceptions +'" id="lesson_structure_subject_' + num_lesson_structure_exceptions +'">';

	for (var i = 0; i < all_subjects.length; i++) {
		new_exts += '<OPTION id="lesson_structure_' + all_subjects[i] + '_' + num_lesson_structure_exceptions + '" onclick="lesson_structure_changed(' + num_lesson_structure_exceptions + ')">' + all_subjects[i] + '</OPTION>';
	}

	new_exts += '</SELECT>';
	//classes
	new_exts += '<TR><TD><LABEL>Classes</LABEL><TD>';

	for (var j = 0; j < all_classes.length; j++) {
		new_exts += '<INPUT id="lesson_structure_' + all_classes[j] + '_' + num_lesson_structure_exceptions + '" type="checkbox" onclick="lesson_structure_changed(' + num_lesson_structure_exceptions + ')">&nbsp;' + all_classes[j] + '&nbsp;&nbsp;&nbsp;';
	}

	//structure
	new_exts += '<TR><TD><span id="error_lesson_structure_' + num_lesson_structure_exceptions + '" style="color: red"></span><LABEL for="lesson_structure_struct_' + num_lesson_structure_exceptions + '">Lesson structure</LABEL><TD><INPUT type="text" name="lesson_structure_struct_' + num_lesson_structure_exceptions + '" id="lesson_structure_struct_' + num_lesson_structure_exceptions + '" onkeyup="lesson_structure_changed(' + num_lesson_structure_exceptions + ')" size="30">';		

	new_exts += '</TABLE><HR>';

	var new_exts_span = document.createElement("span");
	new_exts_span.innerHTML = new_exts;
	document.getElementById("lesson_structure_exceptions").appendChild(new_exts_span);
}

function remove_simultaneous_lesson_association(simult, lesson) {
	
	var current_lessons = [];
	var loc = -1;
	for (var i = 0; i < simult_lessons.length; i++) {
		if (simult_lessons[i].name == simult) {	
			loc = i;
			current_lessons = (simult_lessons[i].value).split(",");
			break;
		}
	}

	var change_made = false;	
	for (var j = 0; j < current_lessons.length; j++) {	
		if (current_lessons[j] == lesson) {
			current_lessons.splice(j,1);
			change_made = true;
			break;
		}
	}

	if (change_made) {
		//update JS copy
		var new_val = current_lessons.join(",");
		simult_lessons[loc].value = new_val;

		//grey out
		document.getElementById("label_simultaneous_lesson_associations_" + simult + "_" + lesson).style.color = "grey";
		document.getElementById("button_simultaneous_lesson_associations_" + simult + "_" + lesson).disabled = true;

		changed["lesson_associations_simultaneous_" + simult] = true;
		changed_flag++;
	
		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = current_lessons.join(",");
		
		getter_functions["lesson_associations_simultaneous_" + simult] = function() {
			changed["lesson_associations_simultaneous_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function remove_mut_ex_lesson_association(simult, lesson) {
	var current_lessons = [];
	var loc = -1;
	for (var i = 0; i < mut_ex_lessons.length; i++) {
		if (mut_ex_lessons[i].name == simult) {	
			loc = i;
			current_lessons = (mut_ex_lessons[i].value).split(",");
			break;
		}
	}

	var change_made = false;	
	for (var j = 0; j < current_lessons.length; j++) {	
		if (current_lessons[j] == lesson) {
			current_lessons.splice(j,1);
			change_made = true;
			break;
		}
	}

	if (change_made) {
		//update JS copy
		var new_val = current_lessons.join(",");
		mut_ex_lessons[loc].value = new_val;

		//grey out
		document.getElementById("label_mut_ex_lesson_associations_" + simult + "_" + lesson).style.color = "grey";
		document.getElementById("button_mut_ex_lesson_associations_" + simult + "_" + lesson).disabled = true;

		changed["lesson_associations_mut_ex_" + simult] = true;
		changed_flag++;
	
		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = current_lessons.join(",");
		
		getter_functions["lesson_associations_mut_ex_" + simult] = function() {
			changed["lesson_associations_mut_ex_" + simult] = false;
			return new_lessons_str;
		}
	}	
}

function remove_occasional_joint_lesson_association(simult, lesson) {
	var current_lessons = [];
	var loc = -1;
	for (var i = 0; i < occasional_joint_lessons.length; i++) {
		if (occasional_joint_lessons[i].name == simult) {	
			loc = i;
			current_lessons = (occasional_joint_lessons[i].lessons).split(",");
			break;
		}
	}

	var change_made = false;	
	for (var j = 0; j < current_lessons.length; j++) {	
		if (current_lessons[j] == lesson) {
			current_lessons.splice(j,1);
			change_made = true;
			break;
		}
	}

	if (change_made) {
		//update JS copy
		var new_val = current_lessons.join(",");
		occasional_joint_lessons[loc].value = new_val;

		//grey out
		document.getElementById("label_occasional_joint_lesson_associations_" + simult + "_" + lesson).style.color = "grey";
		document.getElementById("button_occasional_joint_lesson_associations_" + simult + "_" + lesson).disabled = true;

		changed["lesson_associations_occasional_joint_lessons_" + simult] = true;
		changed_flag++;
	
		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = current_lessons.join(",");
		
		getter_functions["lesson_associations_occasional_joint_lessons_" + simult] = function() {
			changed["lesson_associations_occasional_joint_lessons_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function remove_consecutive_lesson_association(simult, lesson) {
	var current_lessons = [];
	var loc = -1;
	for (var i = 0; i < consecutive_lessons.length; i++) {
		if (consecutive_lessons[i].name == simult) {	
			loc = i;
			current_lessons = (consecutive_lessons[i].value).split(",");
			break;
		}
	}

	var change_made = false;
	for (var j = 0; j < current_lessons.length; j++) {	
		if (current_lessons[j] == lesson) {
			current_lessons.splice(j,1);
			change_made = true;
			break;
		}
	}

	if (change_made) {
		//update JS copy
		var new_val = current_lessons.join(",");
		consecutive_lessons[loc].value = new_val;

		//grey out
		document.getElementById("label_consecutive_lesson_associations_" + simult + "_" + lesson).style.color = "grey";
		document.getElementById("button_consecutive_lesson_associations_" + simult + "_" + lesson).disabled = true;

		changed["lesson_associations_consecutive_" + simult] = true;
		changed_flag++;
	
		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = current_lessons.join(",");
		
		getter_functions["lesson_associations_consecutive_" + simult] = function() {
			changed["lesson_associations_consecutive_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function occasional_joint_lesson_format_changed(simult) {
	var format = document.getElementById("occasional_joint_lessons_format_" + simult).value;
	
	var format_re = /^[0-9]*\\s*x?\\s*[0-9]*\$/;

	//partial match
	if (format.match(format_re)) {
		//clear error
		document.getElementById("error_occasional_joint_lesson_associations_format_" + simult).innerHTML = "";

		//full match
		var full_format_re = /^[0-9]+\\s*x\\s*[0-9]+\$/;
		if (format.match(full_format_re) ) {
			changed["lesson_associations_occasional_joint_format_" + simult] = true;
			changed_flag++;
	
			document.getElementById("save_changes").disabled = false;
	
			getter_functions["lesson_associations_occasional_joint_format_" + simult] = function() {
				changed["lesson_associations_occasional_joint_format_" + simult] = false;
				return format;
			}
		}
	}
	else {
		document.getElementById("error_occasional_joint_lesson_associations_format_" + simult).innerHTML = "*";
	}
}

function new_simultaneous_lesson_association_changed(simult) {

	var new_lessons = new Array();

	var add_cnts = -1;

	for (var l = 0; l < simult_add_cnts.length; l++) {
		if (simult_add_cnts[l].id == simult) {
			add_cnts = simult_add_cnts[l].cnt;
			break;
		}
	}

	for (var k = 0; k < add_cnts; k++) {

		var subj = "";
		for (var i = 0; i < all_subjects.length; i++) {
			if ( document.getElementById("new_simultaneous_lesson_associations_" + all_subjects[i] + "_" + simult + "_" + k ).selected ) {
				subj = all_subjects[i];
				break;
			}
		}
	
		if (subj.length > 0) {
			for (var j = 0; j < all_classes.length; j++) {
				if ( document.getElementById("new_simultaneous_lesson_associations_" + all_classes[j] + "_" + simult + "_" + k).checked ) {
					new_lessons.push(subj + "(" + all_classes[j] + ")");				
				}
			}
		}
	}

	if ( new_lessons.length > 0 ) {
		changed["add_lesson_associations_simultaneous_" + simult] = true;
		changed_flag++;

		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = new_lessons.join(",");
		
		getter_functions["add_lesson_associations_simultaneous_" + simult] = function() {
			changed["add_lesson_associations_simultaneous_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function new_mut_ex_lesson_association_changed(simult) {
	var new_lessons = new Array();

	var add_cnts = -1;

	for (var l = 0; l < mut_ex_add_cnts.length; l++) {
		if (mut_ex_add_cnts[l].id == simult) {
			add_cnts = mut_ex_add_cnts[l].cnt;	
			break;
		}
	}

	for (var k = 0; k < add_cnts; k++) {
		
		var subj = "";
		for (var i = 0; i < all_subjects.length; i++) {

			if ( document.getElementById("new_mut_ex_lesson_associations_" + all_subjects[i] + "_" + simult + "_" + k ).selected ) {
				subj = all_subjects[i];
				break;
			}
		}
	
		if (subj.length > 0) {
			for (var j = 0; j < all_classes.length; j++) {
				if ( document.getElementById("new_mut_ex_lesson_associations_" + all_classes[j] + "_" + simult + "_" + k).checked ) {
					new_lessons.push(subj + "(" + all_classes[j] + ")");				
				}
			}
		}
	}

	if ( new_lessons.length > 0 ) {
		changed["add_lesson_associations_mut_ex_" + simult] = true;
		changed_flag++;

		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = new_lessons.join(",");
		
		getter_functions["add_lesson_associations_mut_ex_" + simult] = function() {
			changed["add_lesson_associations_mut_ex_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function new_occasional_joint_lesson_association_changed(simult) {
	var new_lessons = new Array();

	var add_cnts = -1;

	for (var l = 0; l < occasional_joint_add_cnts.length; l++) {
		if (occasional_joint_add_cnts[l].id == simult) {
			add_cnts = occasional_joint_add_cnts[l].cnt;
			break;
		}
	}

	for (var k = 0; k < add_cnts; k++) {
		
		var subj = "";
		for (var i = 0; i < all_subjects.length; i++) {
			if ( document.getElementById("new_occasional_joint_lesson_associations_" + all_subjects[i] + "_" + simult + "_" + k ).selected ) {
				subj = all_subjects[i];
				break;
			}
		}
	
		if (subj.length > 0) {
			for (var j = 0; j < all_classes.length; j++) {
				if ( document.getElementById("new_occasional_joint_lesson_associations_" + all_classes[j] + "_" + simult + "_" + k).checked ) {
					new_lessons.push(subj + "(" + all_classes[j] + ")");				
				}
			}
		}
	}

	if ( new_lessons.length > 0 ) {
		changed["add_lesson_associations_occasional_joint_lessons_" + simult] = true;
		changed_flag++;

		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = new_lessons.join(",");
		
		getter_functions["add_lesson_associations_occasional_joint_lessons_" + simult] = function() {
			changed["add_lesson_associations_occasional_joint_lessons_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function new_consecutive_lesson_association_changed(simult) {
	var new_lessons = new Array();

	var add_cnts = -1;

	for (var l = 0; l < consecutive_add_cnts.length; l++) {
		if (consecutive_add_cnts[l].id == simult) {
			add_cnts = consecutive_add_cnts[l].cnt;
			break;
		}
	}

	for (var k = 0; k < add_cnts; k++) {
		
		var subj = "";
		for (var i = 0; i < all_subjects.length; i++) {
			if ( document.getElementById("new_consecutive_lesson_associations_" + all_subjects[i] + "_" + simult + "_" + k ).selected ) {
				subj = all_subjects[i];
				break;
			}
		}
	
		if (subj.length > 0) {
			for (var j = 0; j < all_classes.length; j++) {
				if ( document.getElementById("new_consecutive_lesson_associations_" + all_classes[j] + "_" + simult + "_" + k).checked ) {
					new_lessons.push(subj + "(" + all_classes[j] + ")");				
				}
			}
		}
	}

	if ( new_lessons.length > 0 ) {
		changed["add_lesson_associations_consecutive_" + simult] = true;
		changed_flag++;

		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = new_lessons.join(",");
		
		getter_functions["add_lesson_associations_consecutive_" + simult] = function() {
			changed["add_lesson_associations_consecutive_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function show_add_simultaneous_lesson_association(simult) {

	//increment_cnt
	var cnt = 0;
	for (var k = 0; k < simult_add_cnts.length; k++) {
		if (simult_add_cnts[k].id == simult) {	
			cnt = simult_add_cnts[k].cnt++;
			break;
		}
	}

 	//not set yet; pre-existing lesson association being edited 
	if (cnt == 0) {	
		simult_add_cnts.push( {id: simult, cnt: 0} );
	}

	var new_lessons = '<LI><P><TABLE>';
	
	new_lessons += '<TR><TD><LABEL for="new_simultaneous_lesson_associations_subject_' + simult + "_" + cnt + '">Subject</LABEL><TD><SELECT name="new_simultaneous_lesson_associations_subject_' + simult + "_" + cnt + '" id="new_simultaneous_lesson_associations_subject_' + simult + "_" + cnt + '" onchange="new_simultaneous_lesson_association_changed(' + simult + ')">';

	for (var i = 0; i < all_subjects.length; i++) {
		new_lessons += '<OPTION id="new_simultaneous_lesson_associations_' + all_subjects[i] + '_' + simult + "_" + cnt + '">' + all_subjects[i] + '</OPTION>';
	}

	new_lessons += '</SELECT>';
	//classes
	new_lessons += '<TR><TD><LABEL>Classes</LABEL><TD>';

	for (var j = 0; j < all_classes.length; j++) {
		new_lessons += '<INPUT id="new_simultaneous_lesson_associations_' + all_classes[j] + '_' + simult + "_" + cnt +  '" type="checkbox" onclick="new_simultaneous_lesson_association_changed(' + simult + ')">&nbsp;' + all_classes[j] + '&nbsp;&nbsp;&nbsp;';
	}
	
	new_lessons += '</TABLE>';

	var new_lessons_span = document.createElement("span");
	new_lessons_span.innerHTML = new_lessons;

	document.getElementById("add_simultaneous_lesson_associations_" + simult).appendChild(new_lessons_span);
}

function show_add_mut_ex_lesson_association(simult) {
	//increment_cnt
	var cnt = 0;
	for (var k = 0; k < mut_ex_add_cnts.length; k++) {
		if (mut_ex_add_cnts[k].id == simult) {	
			cnt = mut_ex_add_cnts[k].cnt++;	
			break;
		}
	}

	//not set yet; pre-existing lesson association being edited 
	if (cnt == 0) {	
		mut_ex_add_cnts.push( {id: simult, cnt: 0} );
	}

	var new_lessons = '<LI><P><TABLE>';
	
	new_lessons += '<TR><TD><LABEL for="new_mut_ex_lesson_associations_subject_' + simult + "_" + cnt + '">Subject</LABEL><TD><SELECT name="new_mut_ex_lesson_associations_subject_' + simult + "_" + cnt + '" id="new_mut_ex_lesson_associations_subject_' + simult + "_" + cnt + '" onchange="new_mut_ex_lesson_association_changed(' + simult + ')">';

	for (var i = 0; i < all_subjects.length; i++) {
		new_lessons += '<OPTION id="new_mut_ex_lesson_associations_' + all_subjects[i] + '_' + simult + "_" + cnt + '">' + all_subjects[i] + '</OPTION>';
	}

	new_lessons += '</SELECT>';
	//classes
	new_lessons += '<TR><TD><LABEL>Classes</LABEL><TD>';

	for (var j = 0; j < all_classes.length; j++) {
		new_lessons += '<INPUT id="new_mut_ex_lesson_associations_' + all_classes[j] + '_' + simult + "_" + cnt +  '" type="checkbox" onclick="new_mut_ex_lesson_association_changed(' + simult + ')">&nbsp;' + all_classes[j] + '&nbsp;&nbsp;&nbsp;';
	}
	
	new_lessons += '</TABLE>';

	var new_lessons_span = document.createElement("span");
	new_lessons_span.innerHTML = new_lessons;
	document.getElementById("add_mut_ex_lesson_associations_" + simult).appendChild(new_lessons_span);
}

function show_add_occasional_joint_lesson_association(simult) {
	//increment_cnt
	var cnt = 0;
	for (var k = 0; k < occasional_joint_add_cnts.length; k++) {
		if (occasional_joint_add_cnts[k].id == simult) {	
			cnt = occasional_joint_add_cnts[k].cnt++;
			break;
		}
	}

 	//not set yet; pre-existing lesson association being edited 
	if (cnt == 0) {	
		occasional_joint_add_cnts.push( {id: simult, cnt: 0} );
	}

	var new_lessons = '<LI><P><TABLE>';
	
	new_lessons += '<TR><TD><LABEL for="new_occasional_joint_lesson_associations_subject_' + simult + "_" + cnt + '">Subject</LABEL><TD><SELECT name="new_occasional_joint_lesson_associations_subject_' + simult + "_" + cnt + '" id="new_occasional_joint_lesson_associations_subject_' + simult + "_" + cnt + '" onchange="new_occasional_joint_lesson_association_changed(' + simult + ')">';

	for (var i = 0; i < all_subjects.length; i++) {
		new_lessons += '<OPTION id="new_occasional_joint_lesson_associations_' + all_subjects[i] + '_' + simult + "_" + cnt + '">' + all_subjects[i] + '</OPTION>';
	}

	new_lessons += '</SELECT>';
	//classes
	new_lessons += '<TR><TD><LABEL>Classes</LABEL><TD>';

	for (var j = 0; j < all_classes.length; j++) {
		new_lessons += '<INPUT id="new_occasional_joint_lesson_associations_' + all_classes[j] + '_' + simult + "_" + cnt +  '" type="checkbox" onclick="new_occasional_joint_lesson_association_changed(' + simult + ')">&nbsp;' + all_classes[j] + '&nbsp;&nbsp;&nbsp;';
	}
	
	new_lessons += '</TABLE>';

	var new_lessons_span = document.createElement("span");
	new_lessons_span.innerHTML = new_lessons;

	document.getElementById("add_occasional_joint_lesson_associations_" + simult).appendChild(new_lessons_span);	
}

function show_add_consecutive_lesson_association(simult) {
	//increment_cnt
	var cnt = 0;
	for (var k = 0; k < consecutive_add_cnts.length; k++) {
		if (consecutive_add_cnts[k].id == simult) {	
			cnt = consecutive_add_cnts[k].cnt++;
			break;
		}
	}
 
	//not set yet; pre-existing lesson association being edited 
	if (cnt == 0) {	
		consecutive_add_cnts.push( {id: simult, cnt: 0} );
	}

	var new_lessons = '<LI><P><TABLE>';
	
	new_lessons += '<TR><TD><LABEL for="new_consecutive_lesson_associations_subject_' + simult + "_" + cnt + '">Subject</LABEL><TD><SELECT name="new_consecutive_lesson_associations_subject_' + simult + "_" + cnt + '" id="new_consecutive_lesson_associations_subject_' + simult + "_" + cnt + '" onchange="new_consecutive_lesson_association_changed(' + simult + ')">';

	for (var i = 0; i < all_subjects.length; i++) {
		new_lessons += '<OPTION id="new_consecutive_lesson_associations_' + all_subjects[i] + '_' + simult + "_" + cnt + '">' + all_subjects[i] + '</OPTION>';
	}

	new_lessons += '</SELECT>';
	//classes
	new_lessons += '<TR><TD><LABEL>Classes</LABEL><TD>';

	for (var j = 0; j < all_classes.length; j++) {
		new_lessons += '<INPUT id="new_consecutive_lesson_associations_' + all_classes[j] + '_' + simult + "_" + cnt +  '" type="checkbox" onclick="new_consecutive_lesson_association_changed(' + simult + ')">&nbsp;' + all_classes[j] + '&nbsp;&nbsp;&nbsp;';
	}
	
	new_lessons += '</TABLE>';

	var new_lessons_span = document.createElement("span");
	new_lessons_span.innerHTML = new_lessons;

	document.getElementById("add_consecutive_lesson_associations_" + simult).appendChild(new_lessons_span);

}
function show_create_simultaneous_lesson_association() {
	num_lesson_associations++;
	
	simult_add_cnts.push( {id: num_lesson_associations, cnt: 0} );
	
	var new_content_span = document.createElement('span');
	new_content_span.id = "add_simultaneous_lesson_associations_" + num_lesson_associations;

	new_content_span.innerHTML = '<LI><p><INPUT type="button" value="Add" id="button_add_simultaneous_lesson_associations_' + num_lesson_associations + '" onclick="show_add_simultaneous_lesson_association(' + num_lesson_associations + ')">';

	var hr = document.createElement('hr');

	document.getElementById("create_simultaneous_lesson_associations").appendChild(new_content_span);
	document.getElementById("create_simultaneous_lesson_associations").appendChild(hr);
} 

function show_create_mut_ex_lesson_association() {
	num_lesson_associations++;
	
	mut_ex_add_cnts.push( {id: num_lesson_associations, cnt: 0} );

	var new_content_span = document.createElement('span');
	new_content_span.id = "add_mut_ex_lesson_associations_" + num_lesson_associations;
	
	
	new_content_span.innerHTML = '<LI><p><INPUT type="button" value="Add" id="button_add_mut_ex_lesson_associations_' + num_lesson_associations + '" onclick="show_add_mut_ex_lesson_association(' + num_lesson_associations + ')">';
	var hr = document.createElement('hr');

	document.getElementById("create_mut_ex_lesson_associations").appendChild(new_content_span);
	document.getElementById("create_mut_ex_lesson_associations").appendChild(hr);
}

function show_create_occasional_joint_lesson_association() {
	num_lesson_associations++;
	
	occasional_joint_add_cnts.push( {id: num_lesson_associations, cnt: 0} );

	var new_content_span = document.createElement('span');
	new_content_span.id = "add_occasional_joint_lesson_associations_" + num_lesson_associations;

	var new_content_html = '<LI><span style="color: red" id="error_occasional_joint_lesson_associations_format_' + num_lesson_associations + '"></span><LABEL>Number of Joint Lessons</LABEL>&nbsp;&nbsp;<INPUT type="text" value="" id="occasional_joint_lessons_format_' + num_lesson_associations + '" onkeyup="occasional_joint_lesson_format_changed(' + num_lesson_associations + ')">';

	new_content_html += '<LI><p><INPUT type="button" value="Add" id="button_add_occasional_joint_lesson_associations_' + num_lesson_associations + '" onclick="show_add_occasional_joint_lesson_association(' + num_lesson_associations + ')">';

	new_content_span.innerHTML = new_content_html;
	var hr = document.createElement('hr');
	
	document.getElementById("create_occasional_joint_lesson_associations").appendChild(new_content_span);
	document.getElementById("create_occasional_joint_lesson_associations").appendChild(hr);
}

function show_create_consecutive_lesson_association() {
	num_lesson_associations++;
	
	consecutive_add_cnts.push( {id: num_lesson_associations, cnt: 0} );

	var new_content = document.getElementById("create_consecutive_lesson_associations").innerHTML;

	var new_content_span = document.createElement('span');
	new_content_span.id = "add_consecutive_lesson_associations_" + num_lesson_associations;

	new_content_span.innerHTML = '<LI><p><INPUT type="button" value="Add" id="button_add_consecutive_lesson_associations_' + num_lesson_associations + '" onclick="show_add_consecutive_lesson_association(' + num_lesson_associations + ')">';
	var hr = document.createElement('hr');

	document.getElementById("create_consecutive_lesson_associations").appendChild(new_content_span);
	document.getElementById("create_consecutive_lesson_associations").appendChild(hr);
}

function show_add_fixed_scheduling_lesson(simult) {

	//increment_cnt
	var cnt = 0;
	for (var k = 0; k < fixed_scheduling_add_cnts.length; k++) {
		if (fixed_scheduling_add_cnts[k].id == simult) {	
			cnt = fixed_scheduling_add_cnts[k].cnt++;
			break;
		}
	}
 
	//not set yet; pre-existing lesson association being edited 
	if (cnt == 0) {	
		fixed_scheduling_add_cnts.push( {id: simult, cnt: 0} );
	}

	var new_lessons = '<P><TABLE>';
	
	new_lessons += '<TR><TD><LABEL for="new_fixed_scheduling_subject_' + simult + "_" + cnt + '">Subject</LABEL><TD><SELECT name="new_fixed_scheduling_subject_' + simult + "_" + cnt + '" id="new_fixed_scheduling_subject_' + simult + "_" + cnt + '" onchange="new_fixed_scheduling_lesson_changed(' + simult + ')">';

	for (var i = 0; i < all_subjects.length; i++) {
		new_lessons += '<OPTION id="new_fixed_scheduling_' + all_subjects[i] + '_' + simult + "_" + cnt + '">' + all_subjects[i] + '</OPTION>';
	}

	new_lessons += '</SELECT>';
	//classes
	new_lessons += '<TR><TD><LABEL>Classes</LABEL><TD>';

	for (var j = 0; j < all_classes.length; j++) {
		new_lessons += '<INPUT id="new_fixed_scheduling_' + all_classes[j] + '_' + simult + "_" + cnt +  '" type="checkbox" onclick="new_fixed_scheduling_lesson_changed(' + simult + ')">&nbsp;' + all_classes[j] + '&nbsp;&nbsp;&nbsp;';
	}
	
	new_lessons += '</TABLE>';

	var new_lessons_span = document.createElement("span");
	new_lessons_span.innerHTML = new_lessons;
	document.getElementById("box_add_fixed_scheduling_lesson_" + simult).appendChild(new_lessons_span);

}

function new_fixed_scheduling_lesson_changed(simult) {

	var new_lessons = new Array();

	var add_cnts = -1;

	for (var l = 0; l < fixed_scheduling_add_cnts.length; l++) {
		if (fixed_scheduling_add_cnts[l].id == simult) {
			add_cnts = fixed_scheduling_add_cnts[l].cnt;
			break;
		}
	}

	for (var k = 0; k <= add_cnts; k++) {
		
		var subj = "";
		for (var i = 0; i < all_subjects.length; i++) {
			if ( document.getElementById("new_fixed_scheduling_" + all_subjects[i] + "_" + simult + "_" + k ).selected ) {
				subj = all_subjects[i];
				break;
			}
		}
	
		if (subj.length > 0) {
			for (var j = 0; j < all_classes.length; j++) {
				if ( document.getElementById("new_fixed_scheduling_" + all_classes[j] + "_" + simult + "_" + k).checked ) {
					new_lessons.push(subj + "(" + all_classes[j] + ")");				
				}
			}
		}
	}

	if ( new_lessons.length > 0 ) {
		changed["add_fixed_scheduling_lessons_" + simult] = true;
		changed_flag++;

		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = new_lessons.join(",");
		
		getter_functions["add_fixed_scheduling_lessons_" + simult] = function() {
			changed["add_fixed_scheduling_lessons_" + simult] = false;
			return new_lessons_str;
		}
	}
}

function remove_fixed_scheduling_lesson(simult, lesson) {
	var current_lessons = [];
	var loc = -1;
	for (var i = 0; i < fixed_scheduling_lessons.length; i++) {
		if (fixed_scheduling_lessons[i].name == simult) {	
			loc = i;
			current_lessons = (fixed_scheduling_lessons[i].lessons).split(",");
			break;
		}
	}

	var change_made = false;
	for (var j = 0; j < current_lessons.length; j++) {	
		if (current_lessons[j] == lesson) {
			current_lessons.splice(j,1);
			change_made = true;
			break;
		}
	}

	if (change_made) {
		//update JS copy
		var new_val = current_lessons.join(",");
		fixed_scheduling_lessons[loc].lessons = new_val;

		//grey out
		document.getElementById("label_fixed_scheduling_lesson_" + simult + "_" + lesson).style.color = "grey";
		document.getElementById("button_fixed_scheduling_lesson_" + simult + "_" + lesson).disabled = true;

		changed["fixed_scheduling_lessons_" + simult] = true;
		changed_flag++;
	
		document.getElementById("save_changes").disabled = false;
	
		var new_lessons_str = current_lessons.join(",");
		
		getter_functions["fixed_scheduling_lessons_" + simult] = function() {
			changed["fixed_scheduling_lessons_" + simult] = false;		
			return new_lessons_str;
		}
	}
}

function checked_fixed_scheduling_day(simult) {
	var trigger_scan = false;	
	for (var j = 0; j < all_days.length; j++) {
		var checked = document.getElementById("checkbox_fixed_scheduling_day_" + simult + "_" + all_days[j]).checked;
		if (checked) {	
			document.getElementById("label_fixed_scheduling_day_" + simult + "_" + all_days[j]).style.color = "";
		}
		else {
			document.getElementById("periods_fixed_scheduling_day_" + simult + "_" + all_days[j]).value = "";
			document.getElementById("label_fixed_scheduling_day_" + simult + "_" + all_days[j]).style.color = "grey";

			trigger_scan = true;
		}
	}
	if (trigger_scan) {
		changed_fixed_scheduling_periods(simult);
	}
}

function changed_fixed_scheduling_periods(simult) {

	var new_periods_arr = [];
	var num_re = new RegExp("^[0-9]+\$");

	for (var j = 0; j < all_days.length; j++) {
		
		var new_value = document.getElementById("periods_fixed_scheduling_day_" + simult + "_" + all_days[j]).value;

		if (new_value.length > 0) {
			
			document.getElementById("checkbox_fixed_scheduling_day_" + simult + "_" + all_days[j]).checked = true;
			document.getElementById("label_fixed_scheduling_day_" + simult + "_" + all_days[j]).style.color = "";

			var periods = new_value.split(",");
			
			var all_matched = true;
			for (var i = 0; i < periods.length; i++) {
				if (! periods[i].match(num_re)) {
					all_matched = false;
					break;
				}
			}
			if (all_matched) {
				new_periods_arr.push(all_days[j] + "(" + new_value + ")");
				document.getElementById("error_periods_fixed_scheduling_day_" + simult + "_" +all_days[j]).innerHTML = "";
			}
			else {
				document.getElementById("error_periods_fixed_scheduling_day_" + simult + "_" +all_days[j]).innerHTML = "*";
			}
		}
		else {	
			document.getElementById("label_fixed_scheduling_day_" + simult + "_" + all_days[j]).style.color = "grey";
			document.getElementById("error_periods_fixed_scheduling_day_" + simult + "_" +all_days[j]).innerHTML = "";
		}
	}

	var new_periods = new_periods_arr.join(";");

	changed["fixed_scheduling_periods_" + simult] = true;
	changed_flag++;
	document.getElementById("save_changes").disabled = false;

	getter_functions["fixed_scheduling_periods_" + simult] = function() {
		changed["fixed_scheduling_periods_" + simult] = false;
		return new_periods;
	}
}

function show_create_fixed_scheduling() {
	num_fixed_scheduling++;
	
	var new_content = document.getElementById("extend_fixed_scheduling").innerHTML;
	
	//lessons
	new_content += '<P><h4>Lessons</h4><p><span id="box_add_fixed_scheduling_lesson_' + num_fixed_scheduling + '"></span>';
	new_content += '<P><INPUT type="button" value="Add" onclick="show_add_fixed_scheduling_lesson(' + num_fixed_scheduling + ')">';

	//periods
	new_content += '<P><h4>Periods</h4><p><TABLE border="1"><THEAD><TH><INPUT type="checkbox" id="checkbox_check_all_fixed_scheduling_days_' + num_fixed_scheduling + '" onclick="check_all_fixed_scheduling_days(' + num_fixed_scheduling + ')"><TH>Day<TH>Periods</THEAD><TBODY>';

	for (var i = 0; i < all_days.length; i++) {
		new_content += '<TR><TD><INPUT type="checkbox" id="checkbox_fixed_scheduling_day_' + num_fixed_scheduling + '_' + all_days[i] + '" onclick="checked_fixed_scheduling_day(' + num_fixed_scheduling + ')"><TD><LABEL id="label_fixed_scheduling_day_' + num_fixed_scheduling + '_' + all_days[i] + '" style="color: grey">' + all_days[i] + '</LABEL><TD><span id="error_periods_fixed_scheduling_day_' + num_fixed_scheduling + '_' + all_days[i] + '" style="color: red"></span><INPUT type="text" value="" id="periods_fixed_scheduling_day_' + num_fixed_scheduling + '_' + all_days[i] + '" onkeyup="changed_fixed_scheduling_periods(' + num_fixed_scheduling + ')">';
	}
	new_content += '</TBODY></TABLE><HR>';
	document.getElementById("extend_fixed_scheduling").innerHTML = new_content;
}

function check_all_fixed_scheduling_days(cntr) {
	var all_checked = document.getElementById("checkbox_check_all_fixed_scheduling_days_" + cntr).checked;	

	if (!all_checked) {
		changed["fixed_scheduling_periods_" + cntr] = true;
		changed_flag++;
		document.getElementById("save_changes").disabled = false;

		getter_functions["fixed_scheduling_periods_" + cntr] = function() {
			changed["fixed_scheduling_periods_" + cntr] = false;
			return "";
		}
	}

	for (var i = 0; i < all_days.length; i++) {
		document.getElementById("checkbox_fixed_scheduling_day_" + cntr + "_" + all_days[i]).checked = all_checked;	
		//grey
		if (all_checked) {
			document.getElementById("label_fixed_scheduling_day_" + cntr + "_" + all_days[i]).style.color = "";
		}
		//clear values and grey
		else {
			document.getElementById("label_fixed_scheduling_day_" + cntr + "_" + all_days[i]).style.color = "grey";	
			document.getElementById("periods_fixed_scheduling_day_" + cntr + "_" + all_days[i]).value = "";	
		}
	}
}

function changed_teachers_number_free_afternoons() {
	var new_val = document.getElementById("teachers_number_free_afternoons").value;
	if (new_val.match(new RegExp("^[0-9]+\$"))) {
		document.getElementById("error_teachers_number_free_afternoons").innerHTML = "";
		changed["teachers_number_free_afternoons"] = true;
		changed_flag++;
		document.getElementById("save_changes").disabled = false;

		getter_functions["teachers_number_free_afternoons"] = function() {
			changed["teachers_number_free_afternoons"] = false;
			return new_val;
		}
	}
	else {
		document.getElementById("error_teachers_number_free_afternoons").innerHTML = "*";
	}
}

function changed_teachers_number_free_mornings() {
	var new_val = document.getElementById("teachers_number_free_mornings").value;
	if (new_val.match(new RegExp("^[0-9]+\$"))) {
		document.getElementById("error_teachers_number_free_mornings").innerHTML = "";
		changed["teachers_number_free_mornings"] = true;
		changed_flag++;
		document.getElementById("save_changes").disabled = false;

		getter_functions["teachers_number_free_mornings"] = function() {
			changed["teachers_number_free_mornings"] = false;
			return new_val;
		}
	}
	else {
		document.getElementById("error_teachers_number_free_mornings").innerHTML = "*";
	}
}

function changed_teachers_maximum_consecutive_lessons() {
	var new_val = document.getElementById("teachers_maximum_consecutive_lessons").value;
	if (new_val.match(new RegExp("^[0-9]+\$"))) {
		document.getElementById("error_teachers_maximum_consecutive_lessons").innerHTML = "";
		changed["teachers_maximum_consecutive_lessons"] = true;
		changed_flag++;
		document.getElementById("save_changes").disabled = false;

		getter_functions["teachers_maximum_consecutive_lessons"] = function() {
			changed["teachers_maximum_consecutive_lessons"] = false;
			return new_val;
		}
	}
	else {
		document.getElementById("error_teachers_maximum_consecutive_lessons").innerHTML = "*";
	}
}

function changed_maximum_number_doubles() {
	var new_val = document.getElementById("maximum_number_doubles").value;
	if ( new_val.match(new RegExp("^[0-9]+\$")) ) {
		document.getElementById("error_maximum_number_doubles").innerHTML = "";
		changed["maximum_number_doubles"] = true;
		changed_flag++;
		document.getElementById("save_changes").disabled = false;

		getter_functions["maximum_number_doubles"] = function() {
			changed["maximum_number_doubles"] = false;
			return new_val;
		}
	}
	else {
		document.getElementById("error_maximum_number_doubles").innerHTML = "*";
	}

}

function save() {
	if (changed_flag > 0) {
		var new_content = "<em>Clicking confirm will update the following fields in the profile:<ol></em>";

		var form = "<FORM action='/cgi-bin/edittimetableprofiles.cgi?profile=$profile' method='POST'>";
		form += "<INPUT type='hidden' name='confirm_code' value='$conf_code'>";
 
		for ( var has_changed in changed ) {	
			if (changed[has_changed]) {
				new_content += "<li>" + has_changed;
				var new_value = getter_functions[has_changed].call();		
				form += "<INPUT type='hidden' name='" + has_changed + "' value='" + new_value + "'>";
			}
		}
		
		//values have been reset by getter function.
			
		new_content += "</ol>";
		new_content += form;

		new_content += "<INPUT type='submit' name='confirm' value='Confirm'>&nbsp;&nbsp;<INPUT type='button' onclick='cancel()' name='cancel_changes' value='Cancel'>";

		old_content = document.getElementById("pre_conf").innerHTML;
		document.getElementById("pre_conf").innerHTML = new_content; 
	}
}


function cancel() {
	document.getElementById("pre_conf").innerHTML = old_content;
}

</SCRIPT>
%;
		$content .=
qq%
$js
</head>
<body>
$header
<div id="pre_conf">
$body
</div>
</body>
</html>
%;
	}
	else {
		$feedback .= qq%<P><SPAN style="color: red">The profile requested does not exist.</SPAN>%;
		$mode = 0;
		last DISPLAY_FOR_EDITING;
	}
}
}
#create new
if ($mode == 2) {
	my $existing_profiles_js_str = "[]";
	my $template_selection = "";

	if (keys %existing_profiles) {
		$template_selection .= qq%<TR><TD><LABEL for="template">Template</LABEL><TD><SELECT name="template">%;
		my @existing_profiles_js_bts = ();

		for my $profile (keys %existing_profiles) {
			my $profile_name = ${$existing_profiles{$profile}}{"name"};
			$template_selection .= qq%<OPTION value="$profile">% . htmlspecialchars($profile_name) . qq%</OPTION>%;
			push @existing_profiles_js_bts, qq%"$profile_name"%;
		}
		$template_selection .= "</SELECT>";

		$existing_profiles_js_str = "[" . join(", ", @existing_profiles_js_bts) . "]"; 
	}

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content .=
qq%
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable Profile</title>
<SCRIPT type="text/javascript">

var existing_profiles = $existing_profiles_js_str;

function check_name() {
	//reset error msgs
	document.getElementById("name_issue_asterisk") = ""; 
	document.getElementById("name_issue_msg").innerHTML = "";

	var name = document.getElementById("profile_name").value;
	var name_length = name.length();

	if (name_length > 0) {
		//too long
		if (name_length > 32) {
			document.getElementById("name_issue_asterisk") = "*"; 
			document.getElementById("name_issue_msg").innerHTML = "This profile name is too long.";
			return;
		}

		//check collision
		for (var i = 0; i < existing_profiles.length; i++) {
			//collision
			if (name == existing_profiles[i]) {
				document.getElementById("name_issue_asterisk") = "*"; 
				document.getElementById("name_issue_msg").innerHTML = "There's already a profile with this name. You can still re-use this name, but I wouldn't recommend that.";
				return;
			}
		}
	}

	else {
		document.getElementById("name_issue_asterisk") = "*"; 
		document.getElementById("name_issue_msg").innerHTML = "No profile name provided.";
	}
}

</SCRIPT>
</head>
<body>
$header
$feedback
<P>
<FORM action="/cgi-bin/edittimetableprofiles.cgi?act=new" method="POST">
<TABLE>
<TR>
<TD colspan="2"><SPAN id="name_issue_msg" style="color: red"></SPAN>
<TR>
<TD><SPAN id="name_issue_asterisk" style="color: red"></SPAN><LABEL for="profile_name">Profile Name</LABEL><TD><INPUT name="profile_name" id="profile_name" type="text" value="" onblur="check_name()" size="30" maxlength="32">
$template_selection
<TR><TD><INPUT type="submit" name="create" value="Create Profile">
</TABLE>
<INPUT type="hidden" name="confirm_code" value="$conf_code">
</FORM>
%;

}
#display options
if ($mode == 0) {
	
	$content .=
qq%
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Timetable Profile</title>
</head>
<body>
$header
$feedback
<p>Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi?act=new">Create a new profile</a>?
%;
	if (keys %existing_profiles) {
		$content .= "<p>Or edit one of the existing ones:<ul>";
		foreach (keys %existing_profiles) {
			my $time_str = "";

			my $time_secs = ${$existing_profiles{$_}}{"time"};
			if ($time_secs =~ /^\d+$/) {
				my @time = localtime($time_secs);
				my $time_str .= "(Created on " .  sprintf "%02d/%02d/%d at %02d%02d.%02d)", $time[3], $time[4]+1, $time[5]+1900, $time[2],$time[1],$time[0];
			}
			$content .= qq*<li><a href="/cgi-bin/edittimetableprofiles.cgi?profile=$_">${$existing_profiles{$_}}{"name"}</a>$time_str*;
		} 
	}
	else {
		$content .= "<p><em>No profiles have been created yet.</em>";
	}
	$content .= "</body></html>";
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

 
